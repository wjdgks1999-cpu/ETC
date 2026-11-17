"""평가값을 임계값과 비교하고 검토용 요약 Excel을 작성한다."""

import pandas as pd

from data_io import metadata_sheet, write_workbook
from metrics import METRICS
from thresholds import package_versions


def matrix_sheet(matrix):
    """업무 컬럼명과 충돌하지 않는 행 이름을 붙여 관계 행렬을 저장한다."""
    label = "행 컬럼"
    while label in matrix.columns:
        label = "_" + label
    return matrix.rename_axis(label).reset_index()


def judge(result, thresholds):
    """전체 원본의 위험도를 재보정하지 않고 비교하며 평가 불가를 구분한다."""
    rows = []
    for key, (label, operator) in METRICS.items():
        value = result.scores[key]
        if value is None:
            status = "평가 불가"
        else:
            passed = value >= thresholds[key] if operator == "이상" else value <= thresholds[key]
            status = "통과" if passed else "미달"
        rows.append({"평가 지표": label, "측정값": value, "임계값": thresholds[key],
                     "합격 기준": operator, "판정": status})
    summary = pd.DataFrame(rows)
    if "평가 불가" in summary["판정"].values:
        overall = "평가 불가"
    else:
        overall = "통과" if (summary["판정"] == "통과").all() else "미달"
    return summary, overall


def save_evaluation(path, result, summary, overall, context, synthetic_rows, overwrite=False):
    """레코드 없이 요약·분포·관계 행렬·실행 정보를 저장한다."""
    info = {**context, "status": overall, "synthetic_rows": synthetic_rows,
            "matched_count": result.matched_count, "issues": result.issues,
            "scope": "구별 위험도·일차원 분포·이차원 관계만 평가. 연결·추론 위험도 미평가."}
    sheets = {"summary": summary, "columns": result.columns, "pairs": result.pairs,
              "original_relationships": matrix_sheet(result.original_matrix),
              "synthetic_relationships": matrix_sheet(result.synthetic_matrix),
              "relationship_difference": matrix_sheet(result.difference_matrix),
              "context": metadata_sheet(info), "versions": metadata_sheet(package_versions())}
    write_workbook(path, sheets, overwrite)
