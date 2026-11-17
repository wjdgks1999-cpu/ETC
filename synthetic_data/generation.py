"""두 SDV 모델의 생성 결과를 품질 점수로 비교하고 선택한다."""

from dataclasses import dataclass
import math
import random
import warnings

import numpy as np
import pandas as pd

from config import WorkflowError
from data_io import metadata_sheet, validate_table, write_workbook
from thresholds import package_versions

TABLE_NAME = "source"


@dataclass
class GenerationResult:
    """선택한 합성데이터와 모델 비교·메타데이터·경고 개수를 보관한다."""

    data: pd.DataFrame
    selected_model: str
    scores: pd.DataFrame
    column_details: pd.DataFrame
    pair_details: pd.DataFrame
    metadata: dict
    warning_count: int


def choose_model(scores):
    """유한한 두 점수를 비교하며 동점이면 GaussianCopula를 선택한다."""
    if set(scores) != {"gaussian", "ctgan"} or any(
        not math.isfinite(value) or not 0 <= value <= 1 for value in scores.values()
    ):
        raise WorkflowError("두 모델의 유효한 품질 점수를 얻지 못했습니다. 결과를 저장하지 않습니다.")
    return "gaussian" if scores["gaussian"] >= scores["ctgan"] else "ctgan"


def build_metadata(origin, settings):
    """SDV 메타데이터를 추론한 뒤 설정에 있는 컬럼과 키만 수정·검증한다."""
    from sdv.metadata import Metadata

    if set(settings.metadata_overrides) - set(origin.columns):
        raise WorkflowError("metadata_overrides에 원본에 없는 컬럼이 있습니다.")
    if settings.primary_key is not None and settings.primary_key not in origin.columns:
        raise WorkflowError("primary_key에 원본에 없는 컬럼이 지정되었습니다.")
    metadata = Metadata.detect_from_dataframes({TABLE_NAME: origin}, infer_keys="primary_only")
    for column, options in settings.metadata_overrides.items():
        metadata.update_column(column_name=column, table_name=TABLE_NAME, **options)
    if settings.primary_key is not None:
        metadata.set_primary_key(column_name=settings.primary_key, table_name=TABLE_NAME)
    metadata.validate()
    metadata.validate_data({TABLE_NAME: origin})
    return metadata


def generate(origin, settings, progress=None):
    """로컬에서 두 모델을 학습·샘플링하며 예외에 원본 값이 노출되지 않게 한다."""
    origin = validate_table(origin)
    if origin.isna().all().any():
        raise WorkflowError("유효값이 전혀 없는 컬럼은 생성 전에 처리 방안을 정해야 합니다.")
    try:
        from faker import Faker
        from sdv.evaluation import evaluate_quality
        from sdv.single_table import CTGANSynthesizer, GaussianCopulaSynthesizer
        import torch
    except ImportError as error:
        raise WorkflowError("생성 패키지가 없습니다. requirements.txt를 설치하세요.") from error
    scores, candidates, reports = {}, {}, {}
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            metadata = build_metadata(origin, settings)
            for name in ("gaussian", "ctgan"):
                if progress is not None:
                    progress(f"{name}: 학습·생성·품질 평가 중")
                random.seed(settings.generation_seed)
                np.random.seed(settings.generation_seed)
                torch.manual_seed(settings.generation_seed)
                Faker.seed(settings.generation_seed)
                options = {"metadata": metadata, "locales": list(settings.locales)}
                model = (GaussianCopulaSynthesizer(**options) if name == "gaussian" else
                         CTGANSynthesizer(**options, epochs=settings.epochs, verbose=False,
                                         enable_gpu=settings.enable_gpu))
                model.fit({TABLE_NAME: origin})
                # SDV의 중간 CSV 출력은 사용하지 않고 완성된 Excel만 저장한다.
                sampled = model.sample(num_rows=settings.num_rows, output_folder_path=None)[TABLE_NAME]
                if len(sampled) != settings.num_rows or set(sampled.columns) != set(origin.columns):
                    raise WorkflowError("요청한 행 수와 컬럼을 생성하지 못했습니다.")
                candidates[name] = sampled.loc[:, origin.columns]
                reports[name] = evaluate_quality(
                    real_data={TABLE_NAME: origin}, synthetic_data={TABLE_NAME: candidates[name]},
                    metadata=metadata, verbose=False,
                )
                scores[name] = float(reports[name].get_score())
            selected = choose_model(scores)
            column_details = reports[selected].get_details(property_name="Column Shapes")
            pair_details = reports[selected].get_details(property_name="Column Pair Trends")
        return GenerationResult(
            candidates[selected], selected,
            pd.DataFrame([{"모델": key, "품질 점수": value, "선택": key == selected}
                          for key, value in scores.items()]),
            column_details, pair_details, metadata.to_dict(), len(captured),
        )
    except WorkflowError:
        raise
    except Exception as error:
        raise WorkflowError("모델 생성·평가가 실패했습니다. 메타데이터·컬럼 유형·학습 조건을 확인하세요. "
                            f"오류 유형: {type(error).__name__}. 원본 값과 예외 원문은 출력하지 않습니다.") from error


def save_generation(path, result, settings, context, overwrite=False):
    """선택한 데이터와 품질·설정 정보를 동일한 Excel 파일에 저장한다."""
    info = {**context, "selected_model": result.selected_model,
            "selection": "SDV quality score; gaussian wins ties; not a privacy approval",
            "generation": {"num_rows": settings.num_rows, "epochs": settings.epochs,
                           "locales": list(settings.locales), "seed": settings.generation_seed,
                           "enable_gpu": settings.enable_gpu},
            "library_warning_count": result.warning_count}
    write_workbook(path, {"data": result.data, "model_scores": result.scores,
                          "column_shapes": result.column_details, "column_pair_trends": result.pair_details,
                          "context": metadata_sheet(info), "metadata": metadata_sheet(result.metadata),
                          "versions": metadata_sheet(package_versions())}, overwrite)
