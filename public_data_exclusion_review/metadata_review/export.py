"""원본 메타데이터와 최종·중간 검토 결과를 Excel로 저장한다."""

from pathlib import Path
import os
import tempfile
import pandas as pd
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from .schemas import InputError

def save_excel(table_df: pd.DataFrame, records: list[dict], path: Path) -> None:
    """원본 목록에 최종 결과·초안·교정 내역·미해결 사항을 붙여 Excel 하나로 저장한다."""
    if len(table_df) != len(records):
        raise InputError("입력 테이블 수와 결과 행 수가 일치하지 않습니다.")
    path = Path(path)
    rows = []
    for record in records:
        final = record["final"] or {}
        draft = record["draft"] or {}
        corrected = record["corrected"] or {}
        rows.append({
            "처리상태": record["status"],
            "검토결론": "개방 제외" if final.get("exclusion_code") else "판단 보류",
            "제외코드": final.get("exclusion_code"),
            "제외사유": final.get("exclusion_reason", ""),
            "추가검토필요": final.get("review_required"),
            "검토의견": final.get("review_comment", ""),
            "검수지적사항": "\n".join(record["review_issues"]),
            "미해결사항": "\n".join(record["unresolved_issues"]),
            "교정횟수": record["correction_count"],
            "초안제외코드": draft.get("exclusion_code"),
            "초안제외사유": draft.get("exclusion_reason", ""),
            "초안추가검토필요": draft.get("review_required"),
            "초안검토의견": draft.get("review_comment", ""),
            "교정제외코드": corrected.get("exclusion_code"),
            "교정제외사유": corrected.get("exclusion_reason", ""),
            "교정추가검토필요": corrected.get("review_required"),
            "교정검토의견": corrected.get("review_comment", ""),
            "오류": record["error"],
        })
    result_df = pd.concat([table_df.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    # 결과 문자열을 Excel 수식으로 해석하지 않고 텍스트로 저장한다.
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "제외사유"
    sheet.append(list(result_df.columns))
    for row in result_df.itertuples(index=False, name=None):
        # 모델 출력에 XML에서 허용하지 않는 제어문자가 있어도 저장이 실패하지 않게 한다.
        values = []
        for value in row:
            if pd.isna(value):
                value = None
            elif isinstance(value, str):
                value = ILLEGAL_CHARACTERS_RE.sub("", value)
            values.append(value)
        sheet.append(values)
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, str):
                cell.data_type = "s"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    # 저장이 끝난 파일만 최종 경로로 옮겨 불완전한 xlsx가 남지 않게 한다.
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".review-", suffix=".xlsx", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        workbook.save(temporary)
        temporary.replace(path)
    finally:
        workbook.close()
        temporary.unlink(missing_ok=True)
