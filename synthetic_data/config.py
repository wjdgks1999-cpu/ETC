"""합성데이터 작업의 설정과 공통 오류를 정의한다."""

from dataclasses import dataclass, field
import json
import math
from pathlib import Path


class WorkflowError(ValueError):
    """입력값이나 작업 조건을 고쳐야 하는 오류를 나타낸다."""


@dataclass(frozen=True)
class Settings:
    """명령 간 공유할 경로와 계산·생성 설정을 보관한다."""

    origin_path: Path
    synthetic_path: Path
    threshold_path: Path
    evaluation_path: Path
    column_types: dict = field(default_factory=dict)
    risk_columns: list | None = None
    metadata_overrides: dict = field(default_factory=dict)
    primary_key: str | None = None
    iterations: int = 100
    percentile: float = 90
    threshold_seed: int = 0
    num_rows: int = 10000
    epochs: int = 2000
    locales: tuple = ("ko_KR",)
    generation_seed: int = 0
    enable_gpu: bool = True


def require_keys(data, allowed, label):
    """설정 오타가 기본값으로 대체되지 않도록 객체와 키를 검사한다."""
    if not isinstance(data, dict) or set(data) - set(allowed):
        raise WorkflowError(f"{label}: 객체 형식과 지원하는 설정 키를 확인하세요.")


def integer(value, label, minimum=1, maximum=2**32 - 1):
    """불리언을 제외한 정수의 허용 범위를 검사한다."""
    if type(value) is not int or not minimum <= value <= maximum:
        raise WorkflowError(f"{label}: {minimum}~{maximum} 범위의 정수가 필요합니다.")
    return value


def load_settings(path):
    """JSON을 읽고 경로를 설정 파일 위치 기준으로 해석한다."""
    path = Path(path).resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise WorkflowError("설정 파일을 UTF-8 JSON으로 읽을 수 없습니다.") from error
    require_keys(raw, {
        "origin_path", "synthetic_path", "threshold_path", "evaluation_path",
        "column_types", "risk_columns", "metadata_overrides", "primary_key",
        "threshold", "generation",
    }, "전체 설정")
    paths = {}
    defaults = {"synthetic_path": "outputs/synthetic_data.xlsx",
                "threshold_path": "outputs/threshold_results.xlsx",
                "evaluation_path": "outputs/evaluation_results.xlsx"}
    for key in ("origin_path", "synthetic_path", "threshold_path", "evaluation_path"):
        value = raw.get(key, defaults.get(key))
        if not isinstance(value, str) or not value.strip():
            raise WorkflowError(f"{key}: Excel 파일 경로를 지정하세요.")
        paths[key] = (path.parent / value).resolve()
        if paths[key].suffix.lower() != ".xlsx":
            raise WorkflowError(f"{key}: .xlsx 파일만 지원합니다.")
    if len(set(paths.values())) != len(paths):
        raise WorkflowError("원본·합성·임계값·평가 파일 경로는 서로 달라야 합니다.")

    types = raw.get("column_types", {})
    if (not isinstance(types, dict) or
            any(not isinstance(k, str) or v not in ("numerical", "categorical")
                for k, v in types.items())):
        raise WorkflowError("column_types는 컬럼별 numerical 또는 categorical 객체여야 합니다.")
    risk = raw.get("risk_columns")
    if risk is not None and (not isinstance(risk, list) or not risk or
                            any(not isinstance(c, str) or not c for c in risk) or
                            len(set(risk)) != len(risk)):
        raise WorkflowError("risk_columns는 중복 없는 컬럼 목록 또는 null이어야 합니다.")
    overrides = raw.get("metadata_overrides", {})
    if not isinstance(overrides, dict) or any(
        not isinstance(k, str) or not isinstance(v, dict) for k, v in overrides.items()
    ):
        raise WorkflowError("metadata_overrides는 컬럼별 SDV 메타데이터 객체여야 합니다.")
    primary_key = raw.get("primary_key")
    if primary_key is not None and (not isinstance(primary_key, str) or not primary_key):
        raise WorkflowError("primary_key는 컬럼명 또는 null이어야 합니다.")

    threshold = raw.get("threshold", {})
    generation = raw.get("generation", {})
    require_keys(threshold, {"iterations", "percentile", "seed"}, "threshold")
    require_keys(generation, {"num_rows", "epochs", "locales", "seed", "enable_gpu"}, "generation")
    percentile = threshold.get("percentile", 90)
    if (type(percentile) not in (int, float) or not math.isfinite(percentile)
            or not 0 < percentile < 100):
        raise WorkflowError("percentile은 0보다 크고 100보다 작은 수여야 합니다.")
    locales = generation.get("locales", ["ko_KR"])
    if not isinstance(locales, list) or not locales or any(
        not isinstance(item, str) or not item for item in locales
    ):
        raise WorkflowError("locales는 비어 있지 않은 로케일 문자열 목록이어야 합니다.")
    enable_gpu = generation.get("enable_gpu", True)
    if type(enable_gpu) is not bool:
        raise WorkflowError("enable_gpu는 true 또는 false여야 합니다.")
    iterations = integer(threshold.get("iterations", 100), "iterations", maximum=1048575)
    seed = integer(threshold.get("seed", 0), "threshold.seed", minimum=0)
    if seed + iterations - 1 > 2**32 - 1:
        raise WorkflowError("반복별 난수 시드가 허용 범위를 초과합니다.")
    return Settings(
        **paths, column_types=types, risk_columns=risk,
        metadata_overrides=overrides, primary_key=primary_key,
        iterations=iterations, percentile=float(percentile), threshold_seed=seed,
        num_rows=integer(generation.get("num_rows", 10000), "num_rows", maximum=1048575),
        epochs=integer(generation.get("epochs", 2000), "epochs"), locales=tuple(locales),
        generation_seed=integer(generation.get("seed", 0), "generation.seed", minimum=0),
        enable_gpu=enable_gpu,
    )
