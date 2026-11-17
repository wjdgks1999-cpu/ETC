"""승인된 세 평가 지표를 원본 레코드 출력 없이 계산한다."""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, ks_2samp

from config import WorkflowError
from data_io import align_tables

METRIC_VERSION = "2.0"
METRICS = {
    "single_out": ("구별 위험도", "이하"),
    "similarity_1d": ("1차원 분포 유사도", "이상"),
    "error_2d": ("2차원 관계 오차", "이하"),
}


@dataclass
class MetricResult:
    """평가값과 컬럼·관계별 진단을 보관하며 일치 레코드는 보관하지 않는다."""

    scores: dict
    matched_count: int
    columns: pd.DataFrame
    pairs: pd.DataFrame
    original_matrix: pd.DataFrame
    synthetic_matrix: pd.DataFrame
    difference_matrix: pd.DataFrame
    issues: list


def single_out_risk(origin, synthetic, columns):
    """선택한 컬럼에서 원본에 존재하는 합성 레코드 비율과 건수를 계산한다."""
    if not columns or set(columns) - set(origin.columns):
        raise WorkflowError("위험도 비교 컬럼이 비었거나 입력에 없는 컬럼입니다.")
    original_keys = pd.MultiIndex.from_frame(origin[columns].drop_duplicates())
    synthetic_keys = pd.MultiIndex.from_frame(synthetic[columns])
    count = int(synthetic_keys.isin(original_keys).sum())
    return count / len(synthetic), count


def corrected_split_risk(value):
    """50:50 분할로 얻은 위험도에만 전체 원본 크기 보정을 적용한다."""
    return 1 - (1 - value) ** 2


def distribution_similarity(origin, synthetic, types):
    """유효값 분포를 KS·TVD로 비교하고 결측률과 평가 불가 사유를 반환한다."""
    rows = []
    for col, kind in types.items():
        left, right = origin[col].dropna(), synthetic[col].dropna()
        score, reason = None, ""
        if left.empty or right.empty:
            reason = "한쪽 이상의 유효값이 없음"
        elif kind == "numerical":
            # 한 관측값의 점근 p값은 정의되지 않을 수 있지만 KS 통계량은 계산 가능하다.
            method = "exact" if min(len(left), len(right)) == 1 else "asymp"
            score = float(1 - ks_2samp(left, right, method=method).statistic)
        else:
            left_p = left.value_counts(normalize=True)
            right_p = right.value_counts(normalize=True)
            left_p, right_p = left_p.align(right_p, fill_value=0)
            score = float(np.clip(1 - (left_p - right_p).abs().sum() / 2, 0, 1))
        rows.append({
            "컬럼": col, "유형": kind, "지표": "1-KS" if kind == "numerical" else "1-TVD",
            "점수": round(score, 4) if score is not None else None,
            "원본 결측률": float(origin[col].isna().mean()),
            "합성 결측률": float(synthetic[col].isna().mean()), "평가 불가 사유": reason,
        })
    return pd.DataFrame(rows)


def cramers_v(left, right):
    """고유값이 많은 컬럼도 조밀한 교차표 없이 계산하고 2×2 연속성 보정을 유지한다."""
    left_counts, right_counts = left.value_counts(), right.value_counts()
    left_counts, right_counts = left_counts[left_counts > 0], right_counts[right_counts > 0]
    dimension = min(len(left_counts), len(right_counts)) - 1
    if dimension == 0:
        return 0.0
    if len(left_counts) == len(right_counts) == 2:
        chi2 = chi2_contingency(pd.crosstab(left, right), correction=True)[0]
    else:
        observed = pd.DataFrame({"left": left.to_numpy(), "right": right.to_numpy()})
        counts = observed.groupby(["left", "right"], observed=True).size()
        expected = (counts.index.get_level_values(0).map(left_counts).to_numpy(dtype=float)
                    * counts.index.get_level_values(1).map(right_counts).to_numpy(dtype=float) / len(left))
        # 0 빈도 셀을 포함한 Pearson 카이제곱은 sum(O²/E) - n과 같다.
        chi2 = float(np.sum(counts.to_numpy(dtype=float) ** 2 / expected) - len(left))
    return float(np.sqrt(np.clip(chi2 / (len(left) * dimension), 0, 1)))


def anova_ratio(categories, values):
    """전체 변동 중 집단 간 변동의 비율 SSB/SST를 계산한다."""
    mean = values.mean()
    total = float(((values - mean) ** 2).sum())
    if total == 0:
        return 0.0
    groups = pd.DataFrame({"category": categories.to_numpy(), "value": values.to_numpy()})
    summary = groups.groupby("category", observed=True)["value"].agg(["size", "mean"])
    between = (summary["size"] * (summary["mean"] - mean) ** 2).sum()
    return float(np.clip(between / total, 0, 1))


def pair_relationship(frame, first, second, types):
    """두 컬럼의 완전한 관측값만 사용하여 관계값·관측 수·사유를 반환한다."""
    valid = frame[[first, second]].dropna()
    if len(valid) < 2:
        return None, len(valid), "공동 유효값 2개 미만"
    left, right = valid[first], valid[second]
    if types[first] == types[second] == "numerical":
        if left.nunique() < 2 or right.nunique() < 2:
            return None, len(valid), "수치형 상수 컬럼의 Pearson 관계는 정의되지 않음"
        value = float(left.corr(right))
    elif types[first] == types[second] == "categorical":
        value = cramers_v(left, right)
    elif types[first] == "categorical":
        value = anova_ratio(left, right)
    else:
        value = anova_ratio(right, left)
    if not np.isfinite(value):
        return None, len(valid), "유한한 관계값을 계산할 수 없음"
    return value, len(valid), ""


def relationship_similarity(origin, synthetic, types):
    """전체 차이 행렬의 표준편차와 각 컬럼 쌍의 진단을 계산한다."""
    columns = list(origin.columns)
    original_matrix = pd.DataFrame(np.eye(len(columns)), index=columns, columns=columns)
    synthetic_matrix = original_matrix.copy()
    rows = []
    for i, first in enumerate(columns):
        for second in columns[i + 1:]:
            left, n_left, reason_left = pair_relationship(origin, first, second, types)
            right, n_right, reason_right = pair_relationship(synthetic, first, second, types)
            original_matrix.loc[first, second] = original_matrix.loc[second, first] = left
            synthetic_matrix.loc[first, second] = synthetic_matrix.loc[second, first] = right
            rows.append({
                "컬럼1": first, "컬럼2": second, "원본 관계값": left, "합성 관계값": right,
                "차이 절댓값": abs(left - right) if left is not None and right is not None else None,
                "원본 유효쌍": n_left, "합성 유효쌍": n_right,
                "평가 불가 사유": "; ".join(filter(None, [reason_left, reason_right])),
            })
    pairs = pd.DataFrame(rows, columns=["컬럼1", "컬럼2", "원본 관계값", "합성 관계값",
                                       "차이 절댓값", "원본 유효쌍", "합성 유효쌍", "평가 불가 사유"])
    difference = original_matrix - synthetic_matrix
    valid = len(columns) >= 2 and np.isfinite(difference.to_numpy()).all()
    sigma = float(np.std(difference.to_numpy(), ddof=0)) if valid else None
    return sigma, pairs, original_matrix, synthetic_matrix, difference


def measure(origin, synthetic, types, risk_columns=None):
    """동일 스키마의 두 데이터에서 세 지표를 계산하며 미계산 값을 숨기지 않는다."""
    origin, synthetic = align_tables(origin, synthetic, types)
    risk, count = single_out_risk(origin, synthetic, risk_columns or list(origin.columns))
    columns = distribution_similarity(origin, synthetic, types)
    mean = float(columns["점수"].mean()) if columns["점수"].notna().all() else None
    sigma, pairs, left, right, difference = relationship_similarity(origin, synthetic, types)
    issues = []
    if mean is None:
        issues.append("일차원 분포를 계산할 수 없는 컬럼이 있습니다.")
    if sigma is None:
        issues.append("이차원 관계를 계산할 수 없습니다. 컬럼 수·상수·결측을 확인하세요.")
    return MetricResult({"single_out": risk, "similarity_1d": mean, "error_2d": sigma},
                        count, columns, pairs, left, right, difference, issues)
