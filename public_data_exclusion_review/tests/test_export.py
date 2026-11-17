"""검토 결과의 Excel 저장 형식과 실패 시 원본 보존을 검증한다."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
from openpyxl import load_workbook
from helpers import make_result as result
from metadata_review import export
from metadata_review.pipeline import empty_record

class ExcelTests(unittest.TestCase):
    """수집 문자열과 미확정 결과의 안전한 저장을 확인한다."""
    def test_text_controls_and_tentative_review_comments_are_preserved_safely(self):
        """제어문자·수식 해석을 방지하며 미확정 사유와 검토 의견을 보존하는지 확인한다."""
        table = pd.DataFrame({"테이블한글명":["API KEY 관리"]})
        record = empty_record("API KEY 관리")
        candidate = result(reason="=2+2\x00 제외").model_copy(update={
            "review_required":True, "review_comment":"검토\x0b의견",
        }).model_dump()
        record.update(status="needs_review", draft=candidate, corrected=candidate,
                      final=None, unresolved_issues=["미해결 사항"], correction_count=2)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.xlsx"
            export.save_excel(table, [record], path)
            self.assertEqual(list(Path(temporary).iterdir()), [path])
            workbook = load_workbook(path)
            sheet = workbook.active
            headers = {cell.value:cell.column for cell in sheet[1]}
            reason_cell = sheet.cell(2, headers["교정제외사유"])
            self.assertEqual(reason_cell.value, "=2+2 제외")
            self.assertEqual(reason_cell.data_type, "s")
            self.assertTrue(sheet.cell(2,headers["교정추가검토필요"]).value)
            self.assertEqual(sheet.cell(2,headers["교정검토의견"]).value, "검토의견")
            self.assertIsNone(sheet.cell(2,headers["제외사유"]).value)
            workbook.close()

    def test_failed_save_does_not_replace_existing_output(self):
        """Excel 저장 실패가 기존 결과 파일을 훼손하지 않는지 확인한다."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "result.xlsx"
            path.write_bytes(b"previous result")
            table = pd.DataFrame({"테이블한글명":["API KEY 관리"]})
            with patch.object(export.Workbook,"save",side_effect=OSError("save failed")):
                with self.assertRaises(OSError):
                    export.save_excel(table,[empty_record("API KEY 관리")],path)
            self.assertEqual(path.read_bytes(), b"previous result")
            self.assertEqual(list(Path(temporary).iterdir()), [path])
