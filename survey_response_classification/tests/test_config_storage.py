"""설정 검증과 원본 값·출력 파일의 보존을 검증한다."""

from dataclasses import replace
import json
import os
from pathlib import Path
from unittest.mock import patch

from config import AI_CATEGORIES, GENERAL_CATEGORIES, SurveyError, load_settings, read_api_key
from storage import extract_columns, output_lock, read_table, source_rows, write_workbook
from support import ROOT, SyntheticCase


class ConfigTests(SyntheticCase):
    """두 기본 분류체계와 사용자 설정의 오류 처리를 확인한다."""

    def test_examples_preserve_modes_categories(self):
        """일반 7개·복수 구조와 AI 9개·단일 구조의 기본 설정을 확인한다."""
        general = load_settings(ROOT / "config.general.example.json")
        ai = load_settings(ROOT / "config.ai.example.json")
        self.assertEqual(general.categories, GENERAL_CATEGORIES)
        self.assertEqual(ai.categories, AI_CATEGORIES)
        self.assertEqual(general.model, "gpt-4o-mini")
        self.assertNotEqual(general.fingerprint(), ai.fingerprint())

    def test_invalid_settings(self):
        """키 오타·빈 질문·잘못된 모드·시간·시트·범주를 실행 전에 거부한다."""
        cases = [{"question": " "}, {"mode": "other"}, {"timeout": 0}, {"timeout": True},
                 {"timeout": float("nan")}, {"sheet": -1}, {"sheet": True}, {"unknown": 1},
                 {"categories": []}, {"categories": ["A", "A"]}, {"categories": ["A,B"]}]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(SurveyError):
                load_settings(self.config_file(**changes))

    def test_custom_prompt_and_categories_relative_to_config(self):
        """다른 작업 디렉터리와 무관하게 설정 기준 상대 프롬프트를 읽는다."""
        prompt = self.directory / "custom.md"
        prompt.write_text("{question}\n{answer}\n- 가상범주 : 가상 설명\n", encoding="utf-8")
        config = self.config_file(categories=["가상범주"], prompt_path="custom.md")
        self.assertEqual(load_settings(config).categories, ("가상범주",))

    def test_prompt_variables_and_category_mismatch(self):
        """누락 변수·범주 불일치·추가 변수를 요청 전에 검사한다."""
        prompt = self.directory / "custom.md"
        for content in ("{answer}", "{question}{answer}{secret}", "{question}{answer}\n- A : 설명"):
            prompt.write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaises(SurveyError):
                load_settings(self.config_file(prompt_path="custom.md"))

    def test_key_priority_environment_unchanged(self):
        """키는 환경 변수를 우선하고 명시 파일 조회 후에도 환경을 바꾸지 않는다."""
        path = self.directory / "fake.env"
        path.write_text("OPENAI_API_KEY=test-file-value\n", encoding="utf-8")
        before = dict(os.environ)
        self.assertEqual(read_api_key(path), "test-file-value")
        self.assertEqual(dict(os.environ), before)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-env-value"}):
            self.assertEqual(read_api_key(path), "test-env-value")

    def test_key_missing_and_no_automatic_env(self):
        """키가 없으면 명시적으로 실패하며 자동 env 탐색을 하지 않는다."""
        with self.assertRaises(SurveyError):
            read_api_key()
        with self.assertRaises(SurveyError):
            read_api_key(self.directory / "missing.env")


class StorageTests(SyntheticCase):
    """실제 xlsx 입출력으로 행·문자열·기존 결과 보호를 확인한다."""

    def test_extract_preserves_rows_ids_and_selected_columns(self):
        """빈 응답·앞자리 0·보조 컬럼 결측을 제거하지 않고 원본 행을 보존한다."""
        self.workbook([["001", "가상 응답", None], ["002", None, "x"], [None, "둘째", None]],
                      headers=["id", "answer", "extra"])
        before = self.input.read_bytes()
        self.assertEqual(extract_columns(self.input, self.output, ["id", "answer"]), 3)
        result = read_table(self.output)
        self.assertEqual(result.headers, ["source_row", "id", "answer"])
        self.assertEqual(result.rows, [[2, "001", "가상 응답"], [3, "002", None], [4, None, "둘째"]])
        self.assertEqual(self.input.read_bytes(), before)

    def test_extract_preserves_inherited_source_rows(self):
        """이미 추출된 파일을 다시 선택해도 원본 행 번호를 재부여하지 않는다."""
        self.workbook([[8, "a", "내용"], [20, "b", "내용"]], headers=["source_row", "id", "answer"])
        extract_columns(self.input, self.output, ["answer"])
        self.assertEqual(source_rows(read_table(self.output)), [8, 20])

    def test_invalid_source_rows_and_columns(self):
        """행 번호 중복 및 존재하지 않는 추출 컬럼을 거부한다."""
        self.workbook([[2, "a"], [2, "b"]], headers=["source_row", "answer"])
        with self.assertRaises(SurveyError):
            extract_columns(self.input, self.output, ["answer"])
        with self.assertRaises(SurveyError):
            extract_columns(self.input, self.output, ["missing"])
        self.assertFalse(self.output.exists())

    def test_existing_output_not_overwritten(self):
        """기존 출력 파일은 내용이나 확장자와 무관하게 보호한다."""
        self.workbook([[1, "내용"]])
        self.output.write_bytes(b"preserve")
        with self.assertRaises(SurveyError):
            extract_columns(self.input, self.output, ["answer"])
        self.assertEqual(self.output.read_bytes(), b"preserve")

    def test_atomic_save_failure_keeps_previous_and_cleans_temp(self):
        """파일 교체 실패 시 마지막 저장 파일과 일반 오류 정리를 확인한다."""
        self.workbook([[1, "내용"]], path=self.output)
        before = self.output.read_bytes()
        with patch("storage.os.replace", side_effect=OSError("fake")), self.assertRaises(OSError):
            write_workbook(self.output, {"responses": [["x"], [1]]}, replace=True)
        self.assertEqual(self.output.read_bytes(), before)
        self.assertEqual(list(self.directory.glob(".survey-*")), [])

    def test_publish_collision_keeps_existing(self):
        """최종 확정 시 경로가 충돌해도 기존 결과를 교체하지 않는다."""
        original_link = os.link

        def collide(source, destination):
            """확정 직전 다른 작업이 만든 파일을 모의한다."""
            Path(destination).write_bytes(b"other-run")
            original_link(source, destination)

        with patch("storage.os.link", side_effect=collide), self.assertRaises(FileExistsError):
            write_workbook(self.output, {"responses": [["x"], [1]]})
        self.assertEqual(self.output.read_bytes(), b"other-run")

    def test_formula_like_text_stays_text(self):
        """등호로 시작하는 응답 문자열을 수식으로 바꾸지 않는다."""
        self.workbook([["001", "=가상 응답"]])
        self.assertEqual(read_table(self.input).rows[0][1], "=가상 응답")

    def test_real_formulas_and_duplicate_headers_rejected(self):
        """수식 입력과 중복 헤더를 조용히 값으로 해석하지 않는다."""
        from openpyxl import Workbook

        workbook = Workbook()
        workbook.active.append(["id", "answer"])
        workbook.active.append([1, "=1+1"])
        workbook.save(self.input)
        workbook.close()
        with self.assertRaises(SurveyError):
            read_table(self.input)
        duplicate = self.directory / "duplicate.xlsx"
        self.workbook([[1, 2]], headers=["x", "x"], path=duplicate)
        with self.assertRaises(SurveyError):
            read_table(duplicate)

    def test_long_text_not_truncated(self):
        """Excel 제한보다 긴 원문을 잘라 저장하지 않고 실패시킨다."""
        with self.assertRaises(SurveyError):
            self.workbook([[1, "x" * 32768]])
        self.assertFalse(self.input.exists())

    def test_output_lock_cleans_up_and_rejects_concurrent_work(self):
        """동일 출력의 동시 실행을 거부하고 예외 이후 잠금을 제거한다."""
        with self.assertRaises(RuntimeError):
            with output_lock(self.output):
                with self.assertRaises(SurveyError):
                    with output_lock(self.output):
                        self.fail("중복 잠금이 허용되었습니다.")
                raise RuntimeError("fake")
        self.assertFalse(self.output.with_suffix(".xlsx.lock").exists())

    def test_sheet_selection_and_missing_workbook(self):
        """이름과 번호로 시트를 선택하고 잘못된 입력을 거부한다."""
        self.workbook([[1, "내용"]], sheet="가상시트")
        self.assertEqual(read_table(self.input, "가상시트").sheet, "가상시트")
        for sheet in (1, "missing"):
            with self.subTest(sheet=sheet), self.assertRaises(SurveyError):
                read_table(self.input, sheet)
        with self.assertRaises(SurveyError):
            read_table(self.directory / "missing.xlsx")
