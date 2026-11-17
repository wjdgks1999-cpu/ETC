"""임시 Excel만 사용해 설정·산정 조건·명령·파일 보존을 검증한다."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook

from config import WorkflowError, load_settings
from data_io import metadata_sheet, read_table, resolve_types, write_workbook
from generation import choose_model
from thresholds import calculate_thresholds, evaluation_context, load_thresholds, save_thresholds

ROOT = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    """실제 파일 흐름을 임시 디렉터리로 격리한다."""

    def setUp(self):
        """업무 원본과 무관한 반복 패턴 데이터와 설정을 만든다."""
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.config_path = self.directory / "config.json"
        self.raw = {"origin_path": "original.xlsx", "threshold": {"iterations": 4, "seed": 0}}
        self.config_path.write_text(json.dumps(self.raw), encoding="utf-8")
        self.settings = load_settings(self.config_path)
        self.origin = pd.DataFrame({"x": [0, 1, 2, 3] * 30, "y": [2, 0, 3, 1] * 30,
                                    "category": ["a", "b", "a", "b"] * 30})
        self.origin.to_excel(self.settings.origin_path, index=False)
        self.types = resolve_types(self.origin, {})

    def make_threshold_file(self):
        """가상 원본의 실제 분할 결과를 임계값 Excel로 저장한다."""
        values, samples, context = calculate_thresholds(self.origin, self.types, self.settings)
        save_thresholds(self.settings.threshold_path, values, samples, context)
        return values, samples, context

    def call_cli(self, command, *extra):
        """다른 작업 디렉터리에서 별도 프로세스로 명령을 실행한다."""
        environment = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run([sys.executable, "-B", str(ROOT / "synthetic.py"), command,
                               "--config", str(self.config_path), *extra], cwd=self.directory,
                              env=environment, capture_output=True, text=True, encoding="utf-8", timeout=90)

    def test_defaults_preserve_execution_values(self):
        """기존 실행 기본값과 설정 파일 기준 경로 해석을 확인한다."""
        self.config_path.write_text('{"origin_path":"original.xlsx"}', encoding="utf-8")
        settings = load_settings(self.config_path)
        self.assertEqual((settings.iterations, settings.percentile, settings.num_rows, settings.epochs),
                         (100, 90, 10000, 2000))
        self.assertEqual(settings.origin_path, self.directory / "original.xlsx")

    def test_invalid_config_is_rejected(self):
        """오타·범위 밖 값·경로 충돌·잘못된 형식은 실행 전에 거부한다."""
        invalid = [ {"unknown": 1}, {"threshold": {"iterations": 0}},
                    {"threshold": {"percentile": 100}}, {"threshold": {"percentile": float("nan")}},
                    {"generation": {"epochs": True}}, {"synthetic_path": "original.xlsx"},
                    {"risk_columns": []}, {"generation": {"enable_gpu": "yes"}},
                    {"column_types": {"x": "number"}} ]
        for change in invalid:
            with self.subTest(change=change):
                self.config_path.write_text(json.dumps({"origin_path": "original.xlsx", **change}), encoding="utf-8")
                with self.assertRaises(WorkflowError):
                    load_settings(self.config_path)

    def test_duplicate_excel_header_is_rejected(self):
        """pandas가 자동 변경하는 중복 헤더를 원본 시트에서 검사한다."""
        book = Workbook()
        book.active.append(["same", "same"])
        book.active.append([1, 2])
        path = self.directory / "duplicate.xlsx"
        book.save(path)
        book.close()
        with self.assertRaises(WorkflowError):
            read_table(path)

    def test_threshold_round_trip_and_reproducibility(self):
        """시드와 원본이 같으면 반복값·분위수가 같고 Excel에서 복원된다."""
        values, samples, context = self.make_threshold_file()
        again, again_samples, _ = calculate_thresholds(self.origin, self.types, self.settings)
        self.assertEqual(values, again)
        pd.testing.assert_frame_equal(samples, again_samples)
        restored = load_thresholds(self.settings.threshold_path, context)
        for key in values:
            self.assertAlmostEqual(values[key], restored[key])
        np.testing.assert_allclose(samples["single_out"], 1 - (1 - samples["raw_single_out"]) ** 2)
        self.assertAlmostEqual(values["similarity_1d"], np.percentile(samples["similarity_1d"], 10))

    def test_threshold_rejects_changed_context(self):
        """평가식·원본·유형·비교 컬럼·분위수 변경을 감지한다."""
        _, _, context = self.make_threshold_file()
        for key, value in (("metric_version", "old"), ("origin_digest", "changed"),
                           ("column_types", {}), ("risk_columns", ["x"]), ("threshold", {})):
            with self.subTest(key=key), self.assertRaises(WorkflowError):
                load_thresholds(self.settings.threshold_path, {**context, key: value})
        changed = self.origin.copy()
        changed.loc[0, "x"] = 99
        self.assertNotEqual(evaluation_context(changed, self.types, self.settings), context)

    def test_legacy_threshold_is_rejected(self):
        """평가식 정보를 갖지 않은 이전 Excel을 혼용하지 않는다."""
        pd.DataFrame({"평가 지표": ["구별 위험도"], "임계값": [0.1]}).to_excel(
            self.directory / "legacy.xlsx", index=False)
        with self.assertRaises(WorkflowError):
            load_thresholds(self.directory / "legacy.xlsx", {})

    def test_invalid_threshold_numbers_and_duplicates(self):
        """비유한 임계값·잘못된 방향·중복 지표가 판정에 쓰이지 않는다."""
        _, _, context = self.make_threshold_file()
        original = pd.read_excel(self.settings.threshold_path, sheet_name="thresholds")
        for kind in ("nan", "range", "operator", "duplicate"):
            table = original.copy()
            if kind == "nan":
                table.loc[0, "임계값"] = np.nan
            elif kind == "range":
                table.loc[0, "임계값"] = 1.1
            elif kind == "operator":
                table.loc[0, "합격 기준"] = "이상"
            else:
                table.loc[1, "metric"] = table.loc[0, "metric"]
            write_workbook(self.settings.threshold_path,
                           {"thresholds": table, "context": metadata_sheet(context)}, overwrite=True)
            with self.subTest(kind=kind), self.assertRaises(WorkflowError):
                load_thresholds(self.settings.threshold_path, context)

    def test_bad_split_is_not_silently_skipped(self):
        """계산 불가 분할을 버리고 유리한 임계값을 만들지 않는다."""
        data = pd.DataFrame({"x": [1] * 8, "y": range(8)})
        with self.assertRaises(WorkflowError):
            calculate_thresholds(data, resolve_types(data, {}), self.settings)
        self.assertFalse(self.settings.threshold_path.exists())

    def test_writer_preserves_existing_file_and_supports_opt_in(self):
        """덮어쓰기 기본 거부와 명시적 교체를 검증한다."""
        path = self.directory / "result.xlsx"
        write_workbook(path, {"data": pd.DataFrame({"x": [1]})})
        before = path.read_bytes()
        with self.assertRaises(WorkflowError):
            write_workbook(path, {"data": pd.DataFrame({"x": [2]})})
        self.assertEqual(before, path.read_bytes())
        write_workbook(path, {"data": pd.DataFrame({"x": [2]})}, overwrite=True)
        self.assertEqual(read_table(path).iloc[0, 0], 2)

    def test_failed_save_keeps_previous_result(self):
        """저장 중 오류가 나도 기존 파일과 다른 임시 파일을 보존한다."""
        path = self.directory / "result.xlsx"
        path.write_bytes(b"previous-result")
        with patch.object(pd.DataFrame, "to_excel", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                write_workbook(path, {"data": self.origin}, overwrite=True)
        self.assertEqual(path.read_bytes(), b"previous-result")
        self.assertFalse(list(self.directory.glob(".synthetic-*.xlsx")))

    def test_formula_like_data_is_literal(self):
        """등호로 시작하는 데이터 문자열을 수식으로 저장하지 않는다."""
        path = self.directory / "literal.xlsx"
        write_workbook(path, {"data": pd.DataFrame({"text": ["=1+1"]})})
        book = load_workbook(path, data_only=False)
        self.assertEqual(book.active["A2"].data_type, "s")
        book.close()
        self.assertEqual(read_table(path).iloc[0, 0], "=1+1")

    def test_cli_threshold_evaluate_and_overwrite(self):
        """별도 프로세스에서 산정·평가·중복 출력 거부가 이어진다."""
        calculated = self.call_cli("threshold")
        self.assertEqual(calculated.returncode, 0, calculated.stderr)
        write_workbook(self.settings.synthetic_path, {"data": self.origin})
        evaluated = self.call_cli("evaluate")
        self.assertEqual(evaluated.returncode, 0, evaluated.stderr + evaluated.stdout)
        self.assertNotIn("모든 프라이버시", evaluated.stdout)
        sheets = pd.read_excel(self.settings.evaluation_path, sheet_name=None)
        self.assertIn("relationship_difference", sheets)
        self.assertNotIn("matched_data", sheets)
        duplicate = self.call_cli("evaluate")
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn("--overwrite", duplicate.stderr)
        self.assertEqual(self.call_cli("evaluate", "--overwrite").returncode, 0)

    def test_unavailable_evaluation_is_saved_without_pass(self):
        """합성에 상수 수치 컬럼이 생겨도 평가 불가 보고서를 남긴다."""
        self.make_threshold_file()
        data = self.origin.copy()
        data["x"] = 1
        write_workbook(self.settings.synthetic_path, {"data": data})
        result = self.call_cli("evaluate")
        self.assertEqual(result.returncode, 2)
        self.assertIn("평가 불가", result.stdout)
        self.assertTrue(self.settings.evaluation_path.exists())

    def test_import_does_not_read_train_or_write(self):
        """모듈 import에 데이터 읽기·학습·결과 파일 생성이 없다."""
        code = "import sys; sys.path.insert(0, sys.argv[1]); import synthetic, generation; assert 'sdv' not in sys.modules"
        before = set(self.directory.iterdir())
        result = subprocess.run([sys.executable, "-B", "-c", code, str(ROOT)], cwd=self.directory,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, set(self.directory.iterdir()))

    def test_generation_selection_and_invalid_scores(self):
        """양 모델 선택·Gaussian 동점 우선과 비유한 점수 거부를 확인한다."""
        self.assertEqual(choose_model({"gaussian": .5, "ctgan": .5}), "gaussian")
        self.assertEqual(choose_model({"gaussian": .4, "ctgan": .5}), "ctgan")
        for value in (float("nan"), float("inf"), -1):
            with self.assertRaises(WorkflowError):
                choose_model({"gaussian": value, "ctgan": .5})


if __name__ == "__main__":
    unittest.main()
