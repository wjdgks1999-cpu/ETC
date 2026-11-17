"""반복 분할 임계값과 재사용 가능한 산정 조건을 관리한다."""

import hashlib
import importlib.metadata
import platform

import numpy as np
import pandas as pd

from config import WorkflowError
from data_io import check_types, metadata_sheet, read_metadata, validate_table, write_workbook
from metrics import METRICS, METRIC_VERSION, corrected_split_risk, measure


def package_versions():
    """평가·생성 결과 해석에 필요한 실제 패키지 버전을 반환한다."""
    result = {"python": platform.python_version()}
    for name in ("pandas", "numpy", "scipy", "openpyxl", "sdv", "sdmetrics", "ctgan", "torch"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def evaluation_context(origin, types, settings):
    """원본 내용의 해시와 계산 조건을 만들고 원본 레코드는 저장하지 않는다."""
    digest = hashlib.sha256(pd.util.hash_pandas_object(origin, index=False).to_numpy().tobytes()).hexdigest()
    risk_columns = settings.risk_columns if settings.risk_columns is not None else list(origin.columns)
    if not risk_columns or set(risk_columns) - set(origin.columns):
        raise WorkflowError("risk_columns에 입력에 없는 컬럼이 있습니다.")
    return {
        "metric_version": METRIC_VERSION, "origin_digest": digest,
        "origin_rows": len(origin), "columns": list(origin.columns), "column_types": types,
        "risk_columns": risk_columns,
        "threshold": {"iterations": settings.iterations, "percentile": settings.percentile,
                      "seed": settings.threshold_seed},
        "method": {"single_out": "exact_match; split_correction_only",
                   "similarity_1d": "mean(round(KSComplement_or_TVComplement, 4))",
                   "error_2d": "std(full_difference_matrix, ddof=0); ANOVA=SSB/SST",
                   "cramers_v": "chi2_contingency(correction=True)",
                   "missing": "drop_per_column_or_pair; undefined_metric_blocks_pass"},
    }


def calculate_thresholds(origin, types, settings, progress=None):
    """50:50 분할을 반복하고 모든 반복에서 계산 가능한 경우에만 분위수를 산출한다."""
    origin = validate_table(origin)
    check_types(origin, types)
    if len(origin) < 4:
        raise WorkflowError("50:50 분할 계산에는 최소 4행이 필요합니다.")
    context = evaluation_context(origin, types, settings)
    records = []
    for iteration in range(settings.iterations):
        shuffled = origin.sample(frac=1, random_state=settings.threshold_seed + iteration)
        middle = len(origin) // 2
        result = measure(shuffled.iloc[:middle], shuffled.iloc[middle:], types, settings.risk_columns)
        if result.issues:
            raise WorkflowError(f"{iteration + 1}번째 분할에서 지표를 계산할 수 없습니다. "
                                "컬럼 수·유형·결측·상수 분포를 확인하세요. 임계값을 저장하지 않았습니다.")
        records.append({"iteration": iteration + 1, "raw_single_out": result.scores["single_out"],
                        **result.scores, "single_out": corrected_split_risk(result.scores["single_out"])})
        if progress is not None and ((iteration + 1) % 10 == 0 or iteration + 1 == settings.iterations):
            progress(iteration + 1, settings.iterations)
    samples = pd.DataFrame(records)
    thresholds = {}
    for metric in METRICS:
        quantile = 100 - settings.percentile if metric == "similarity_1d" else settings.percentile
        thresholds[metric] = float(np.percentile(samples[metric], quantile))
    return thresholds, samples, context


def save_thresholds(path, values, samples, context, overwrite=False):
    """임계값·반복 결과·평가식과 실행 버전을 한 Excel에 저장한다."""
    rows = [{"metric": key, "평가 지표": label, "임계값": values[key], "합격 기준": operator}
            for key, (label, operator) in METRICS.items()]
    write_workbook(path, {"thresholds": pd.DataFrame(rows), "simulation": samples,
                          "context": metadata_sheet(context),
                          "versions": metadata_sheet(package_versions())}, overwrite)


def load_thresholds(path, expected_context):
    """임계값의 평가식·원본·설정 일치와 유효 범위를 확인한 뒤 반환한다."""
    try:
        sheets = pd.read_excel(path, sheet_name=["thresholds", "context"], engine="openpyxl")
        context = read_metadata(sheets["context"])
        if context != expected_context:
            raise WorkflowError("임계값의 평가식·원본·설정이 현재 작업과 다릅니다. 다시 산정하세요.")
        table = sheets["thresholds"]
        if (set(table.columns) != {"metric", "평가 지표", "임계값", "합격 기준"}
                or table["metric"].duplicated().any() or set(table["metric"]) != set(METRICS)):
            raise WorkflowError("임계값 항목이 누락·중복되었거나 형식이 다릅니다. 다시 산정하세요.")
        values = {}
        for row in table.to_dict("records"):
            key = row["metric"]
            value = float(row["임계값"])
            upper = 2 if key == "error_2d" else 1
            if (not np.isfinite(value) or not 0 <= value <= upper or
                    row["합격 기준"] != METRICS[key][1]):
                raise WorkflowError("임계값 또는 비교 방향이 올바르지 않습니다. 다시 산정하세요.")
            values[key] = value
        return values
    except WorkflowError:
        raise
    except Exception as error:
        raise WorkflowError("현재 형식의 임계값 파일을 읽을 수 없습니다. threshold 명령으로 다시 산정하세요.") from error
