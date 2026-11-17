"""가상 Excel로 입력 연결과 비교 준비 단계를 검증한다."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd
from openpyxl import load_workbook

from helpers import write_inputs
from metadata_review.inputs import load_inputs
from metadata_review.schemas import INPUT_COLUMNS, InputError
from metadata_review.comparison import compare_files, read_names


class InputTests(unittest.TestCase):
    """이름 대조, 필수 항목과 모델 전송 범위를 검증한다."""

    def setUp(self):
        """각 검증에 사용할 가상 입력 파일을 만든다."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tables, self.columns = write_inputs(self.root, counts=(3, 3), names=("같은 이름", "같은 이름"))

    def test_match_by_english_name_and_restrict_fields(self):
        """한글명이 같아도 영문명으로 분리하고 허용된 다섯 컬럼만 전달하는지 확인한다."""
        original = pd.read_excel(self.tables)
        original["정보시스템명"] = ["시스템 가", "시스템 나"]
        original["논리DB명"] = ["DB 가", "DB 나"]
        original.to_excel(self.tables, index=False)
        tables, items = load_inputs(self.tables, self.columns)
        self.assertEqual(len(items), 2)
        for item, (_, table) in zip(items, tables.iterrows()):
            self.assertEqual(set(item), {"table_name", "columns_df", "information_system_name", "logical_db_name"})
            rows = json.loads(item["columns_df"])
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(set(row) == set(INPUT_COLUMNS) for row in rows))
            self.assertTrue(all(row["테이블 영문명"] == table["테이블영문명"] for row in rows))
            self.assertEqual(item["information_system_name"], table["정보시스템명"])
            self.assertEqual(item["logical_db_name"], table["논리DB명"])

    def test_whitespace_headers_and_names_match(self):
        """헤더 공백 차이와 영문명 양끝 공백이 연결을 방해하지 않는지 확인한다."""
        tables = pd.read_excel(self.tables)
        tables = tables.rename(columns={"테이블영문명": "테이블 영문명"})
        tables.loc[0, "테이블 영문명"] = " table_0 "
        tables.to_excel(self.tables, index=False)
        _, items = load_inputs(self.tables, self.columns)
        self.assertEqual(len(items), 2)

    def test_missing_and_duplicate_names_fail(self):
        """필수 이름 누락과 공백 제거 후 중복되는 영문명을 거부하는지 확인한다."""
        original = pd.read_excel(self.tables)
        for column, value in (("테이블영문명", " "), ("테이블한글명", None), ("테이블영문명", " table_1 ")):
            with self.subTest(column=column, value=value):
                changed = original.copy()
                changed.loc[0, column] = value
                changed.to_excel(self.tables, index=False)
                with self.assertRaises(InputError):
                    load_inputs(self.tables, self.columns)

    def test_missing_context_header_and_column_info_fail(self):
        """보조 항목 헤더와 연결할 컬럼 정보의 누락을 입력 단계에서 알리는지 확인한다."""
        original = pd.read_excel(self.tables)
        original.drop(columns="정보시스템명").to_excel(self.tables, index=False)
        with self.assertRaisesRegex(InputError, "정보시스템명"):
            load_inputs(self.tables, self.columns)
        original.to_excel(self.tables, index=False)
        columns = pd.read_excel(self.columns)
        columns[columns["테이블 영문명"] != "table_1"].to_excel(self.columns, index=False)
        with self.assertRaisesRegex(InputError, "컬럼 정보가 없는"):
            load_inputs(self.tables, self.columns)

    def test_blank_context_and_unapproved_metadata(self):
        """빈 보조 값은 빈 문자열로 보내고 추가 메타데이터는 모델 입력에서 제외하는지 확인한다."""
        frame = pd.read_excel(self.tables)
        frame["정보시스템명"] = None
        frame["논리DB명"] = None
        frame["기관명"] = "임의 판단 지시"
        frame.to_excel(self.tables, index=False)
        columns = pd.read_excel(self.columns)
        columns["비공개사유"] = "임의 판단 지시"
        columns.to_excel(self.columns, index=False)
        _, items = load_inputs(self.tables, self.columns)
        self.assertTrue(all(item["information_system_name"] == item["logical_db_name"] == "" for item in items))
        self.assertNotIn("임의 판단 지시", json.dumps(items, ensure_ascii=False))

    def test_duplicate_header_is_rejected(self):
        """공백만 다른 중복 헤더가 모호한 입력으로 사용되지 않는지 확인한다."""
        book = load_workbook(self.tables)
        book.active.cell(1, 5, "테이블 영문명")
        book.save(self.tables)
        book.close()
        with self.assertRaisesRegex(InputError, "중복"):
            load_inputs(self.tables, self.columns)

    def test_limit_and_selected_sheet(self):
        """시트 선택과 처리 한도가 적용되며 0 이하 한도는 거부되는지 확인한다."""
        tables, items = load_inputs(self.tables, self.columns, limit=1, table_sheet="Sheet1", column_sheet="Sheet1")
        self.assertEqual((len(tables), len(items)), (1, 1))
        with self.assertRaises(InputError):
            load_inputs(self.tables, self.columns, limit=0)

    def test_comparison_keeps_inputs_and_exports_all_groups(self):
        """비교 시 원본을 보존하고 공통·누락 그룹을 CSV로 저장하는지 확인한다."""
        columns = pd.read_excel(self.columns)
        columns.loc[columns["테이블 영문명"] == "table_1", "테이블 영문명"] = "table_extra"
        columns.to_excel(self.columns, index=False)
        before = {p: hashlib.sha256(p.read_bytes()).digest() for p in (self.tables, self.columns)}
        output = self.root / "comparison.csv"
        with contextlib.redirect_stdout(io.StringIO()):
            groups = compare_files(self.tables, self.columns, output=output)
        self.assertEqual(groups["영문명"]["양쪽 모두 존재"], ["table_0"])
        self.assertEqual(groups["영문명"]["테이블정보에만 존재"], ["table_1"])
        self.assertTrue(output.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertTrue(all(before[p] == hashlib.sha256(p.read_bytes()).digest() for p in before))

    def test_comparison_missing_names_and_source_overwrite(self):
        """이름 누락 행을 기록하고 원본 경로로의 비교 결과 저장을 거부하는지 확인한다."""
        frame = pd.read_excel(self.tables)
        frame.loc[0, "테이블한글명"] = None
        frame.to_excel(self.tables, index=False)
        self.assertEqual(read_names(self.tables).missing[0][0], 2)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            compare_files(self.tables, self.columns, output=self.tables)
