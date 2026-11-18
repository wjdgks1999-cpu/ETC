"""설정과 원본 값·파일 보존 계약을 검증한다."""

from dataclasses import replace
from datetime import datetime
import os
from pathlib import Path
from unittest.mock import patch

from config import CleaningError, DEFAULT_MODEL, load_settings, read_api_key
from storage import output_lock, read_input, write_workbook
from support import ROOT, SyntheticCase


class ConfigTests(SyntheticCase):
    """정제 방식과 모델·프롬프트 설정의 보존을 확인한다."""

    def test_defaults_and_distinct_instructions(self):
        """기존 모델 기본값과 두 정제 작업의 핵심 지시를 보존한다."""
        html = load_settings("html")
        privacy = load_settings("privacy")
        self.assertEqual(html.model, DEFAULT_MODEL)
        self.assertEqual(html.encoding, "cp949")
        self.assertEqual(html.column, "내용")
        self.assertIn("html 양식을 제거하고 내용만을 추출", html.prompt)
        self.assertIn("개인정보가 있는 문구 전체를 삭제", privacy.prompt)
        self.assertNotIn("{target_contents}", privacy.prompt)
        self.assertNotEqual(html.fingerprint(), privacy.fingerprint())

    def test_model_priority_and_environment_unchanged(self):
        """명시 설정·환경 변수·지정 환경 파일·기본값의 우선순위를 확인한다."""
        path = self.directory / "fake.env"
        path.write_text("OPENAI_MODEL=test-file-model\nOPENAI_API_KEY=test-file-key\n", encoding="utf-8")
        before = dict(os.environ)
        self.assertEqual(load_settings("html", env_file=path).model, "test-file-model")
        self.assertEqual(read_api_key(path), "test-file-key")
        self.assertEqual(dict(os.environ), before)
        with patch.dict(os.environ, {"OPENAI_MODEL": "test-env-model", "OPENAI_API_KEY": "test-env-key"}):
            self.assertEqual(load_settings("html", env_file=path).model, "test-env-model")
            self.assertEqual(read_api_key(path), "test-env-key")
            self.assertEqual(load_settings("html", self.config_file(model="explicit"), path).model, "explicit")

    def test_custom_prompt_resolves_relative_to_configuration(self):
        """설정 기준 상대 경로로 사용자 프롬프트를 읽고 중괄호를 그대로 보존한다."""
        path = self.directory / "prompt.md"
        path.write_text("가상 지시 {literal}", encoding="utf-8")
        settings = load_settings("html", self.config_file(prompt_path="prompt.md"))
        self.assertEqual(settings.prompt, "가상 지시 {literal}")

    def test_invalid_configuration(self):
        """설정 오타·빈 값·시트·시간·인코딩 오류를 요청 전에 거부한다."""
        for changes in ({"column": " "}, {"sheet": -1}, {"sheet": True}, {"model": ""},
                        {"timeout": 0}, {"timeout": True}, {"timeout": float("nan")},
                        {"encoding": "unknown-encoding"}, {"unknown": 1}, {"prompt_path": "missing.md"}):
            with self.subTest(changes=changes), self.assertRaises(CleaningError):
                load_settings("html", self.config_file(**changes))
        with self.assertRaises(CleaningError):
            load_settings("unknown")

    def test_no_automatic_env_or_key_requirement_for_settings(self):
        """기본 설정만 읽을 때 키를 요구하지 않고 자동 환경 파일 탐색을 하지 않는다."""
        with patch("dotenv.dotenv_values") as values:
            load_settings("html")
            with self.assertRaises(CleaningError):
                read_api_key()
        values.assert_not_called()
        with self.assertRaises(CleaningError):
            read_api_key(self.directory / "missing.env")

    def test_fingerprint_tracks_operational_changes(self):
        """입력 해석·모델·정제 지시 변경은 재개 식별정보에 반영한다."""
        for changes in ({"mode": "privacy"}, {"column": "other"}, {"encoding": "utf-8"},
                        {"sheet": 1}, {"model": "other"}, {"timeout": 90}, {"prompt": "새 지시"}):
            with self.subTest(changes=changes):
                self.assertNotEqual(self.settings.fingerprint(), replace(self.settings, **changes).fingerprint())


class StorageTests(SyntheticCase):
    """실제 CSV·Excel을 이용해 값 보존과 저장 오류를 확인한다."""

    def test_cp949_csv_preserves_ids_na_and_multiline_content(self):
        """앞자리 0·NA 문자열·쉼표·줄바꿈을 타입 추론 없이 보존한다."""
        path = self.csv_file([["001", '<p>가상, "본문"\r\n둘째 줄</p>'], ["002", "NA"], ["003", ""]])
        table = read_input(path, self.settings)
        self.assertEqual(table.rows, [["001", '<p>가상, "본문"\r\n둘째 줄</p>'], ["002", "NA"], ["003", ""]])
        self.assertEqual(table.source_rows, [2, 3, 4])

    def test_utf8_csv_configuration_and_wrong_encoding(self):
        """UTF-8 입력은 명시된 인코딩으로 읽으며 잘못된 디코딩을 숨기지 않는다."""
        path = self.csv_file([["001", "가상 🙂"]], encoding="utf-8-sig")
        self.assertEqual(read_input(path, replace(self.settings, encoding="utf-8-sig")).rows[0][1], "가상 🙂")
        with self.assertRaises(CleaningError):
            read_input(path, self.settings)

    def test_duplicate_headers_and_ragged_csv_rejected(self):
        """헤더 충돌과 컬럼 수가 어긋나는 CSV를 조용히 보정하지 않는다."""
        for index, content in enumerate(("a,a\nx,y\n", "id,body\n1,a,extra\n", "id,body\n1\n", "id,\n1,a\n")):
            path = self.directory / f"invalid-{index}.csv"
            path.write_text(content, encoding="cp949")
            with self.subTest(content=content), self.assertRaises(CleaningError):
                read_input(path, self.settings)

    def test_blank_csv_records_keep_their_positions(self):
        """CSV의 빈 레코드도 원본 위치를 유지한다."""
        path = self.directory / "blank.csv"
        path.write_text("id,body\n1,first\n\n3,third\n", encoding="cp949")
        table = read_input(path, self.settings)
        self.assertEqual(table.rows[1], ["", ""])
        self.assertEqual(table.source_rows, [2, 3, 4])

    def test_xlsx_sheet_and_other_types_preserved(self):
        """선택한 시트의 문자열 ID·날짜·숫자·결측을 그대로 읽는다."""
        self.workbook([["001", "가상", datetime(2025, 1, 2), 7, None]],
                      headers=["id", "body", "date", "count", "extra"], sheet="선택")
        table = read_input(self.input, replace(self.settings, sheet="선택"))
        self.assertEqual(table.rows[0], ["001", "가상", datetime(2025, 1, 2), 7, None])
        with self.assertRaises(CleaningError):
            read_input(self.input, replace(self.settings, sheet="missing"))

    def test_formulas_rejected_but_formula_like_text_preserved(self):
        """등호 텍스트를 수식으로 바꾸지 않으며 실제 수식은 값 확정을 요구한다."""
        from openpyxl import Workbook

        self.workbook([["001", "=가상 본문"]])
        self.assertEqual(read_input(self.input, self.settings).rows[0][1], "=가상 본문")
        workbook = Workbook()
        workbook.active.append(["id", "body"])
        workbook.active.append([1, "=1+1"])
        path = self.directory / "formula.xlsx"
        workbook.save(path)
        workbook.close()
        with self.assertRaises(CleaningError):
            read_input(path, self.settings)

    def test_unrelated_run_sheet_does_not_mark_input_as_checkpoint(self):
        """일반 입력에 run 이름의 시트가 있어도 이 도구의 실행 결과로 오인하지 않는다."""
        from openpyxl import Workbook

        workbook = Workbook()
        workbook.active.append(["id", "body"])
        workbook.active.append(["001", "가상"])
        other = workbook.create_sheet("run")
        other.append(["unrelated", "=1+1"])
        workbook.save(self.input)
        workbook.close()
        self.assertEqual(read_input(self.input, self.settings).rows[0], ["001", "가상"])

    def test_empty_input_and_unsupported_extension(self):
        """헤더 없는 입력과 지원하지 않는 확장자를 명시적으로 거부한다."""
        for name in ("empty.csv", "input.txt"):
            path = self.directory / name
            path.write_bytes(b"")
            with self.subTest(name=name), self.assertRaises(CleaningError):
                read_input(path, self.settings)

    def test_long_csv_not_truncated_to_excel_limit(self):
        """긴 본문을 자동 절단하지 않고 출력 가능한 길이인지 사전 검증한다."""
        path = self.csv_file([["001", "x" * 32768]])
        with self.assertRaises(CleaningError):
            read_input(path, self.settings)

    def test_existing_output_and_atomic_save_failure(self):
        """기존 결과와 교체 실패 직전의 마지막 저장 내용을 보존한다."""
        self.workbook([[1, "before"]], path=self.output)
        before = self.output.read_bytes()
        with self.assertRaises(CleaningError):
            write_workbook(self.output, {"data": [["id", "body"], [1, "after"]]})
        with patch("storage.os.replace", side_effect=OSError()), self.assertRaises(OSError):
            write_workbook(self.output, {"data": [["id", "body"], [1, "after"]]}, replace=True)
        self.assertEqual(self.output.read_bytes(), before)
        self.assertEqual(list(self.directory.glob(".cleaning-*")), [])

    def test_new_output_collision_preserves_other_file(self):
        """완성 파일 확정 직전에 생긴 다른 결과를 덮어쓰지 않는다."""
        original_link = os.link

        def collide(source, destination):
            """다른 실행이 출력 경로를 먼저 만든 상황을 모의한다."""
            Path(destination).write_bytes(b"other-file")
            original_link(source, destination)

        with patch("storage.os.link", side_effect=collide), self.assertRaises(FileExistsError):
            write_workbook(self.output, {"data": [["id", "body"], [1, "after"]]})
        self.assertEqual(self.output.read_bytes(), b"other-file")

    def test_lock_prevents_concurrent_work_and_cleans_up(self):
        """같은 출력의 동시 실행을 막으며 예외 이후 잠금을 정리한다."""
        with self.assertRaises(RuntimeError):
            with output_lock(self.output):
                with self.assertRaises(CleaningError):
                    with output_lock(self.output):
                        self.fail("중복 잠금 허용")
                raise RuntimeError("synthetic")
        self.assertFalse(self.output.with_name(self.output.name + ".lock").exists())
