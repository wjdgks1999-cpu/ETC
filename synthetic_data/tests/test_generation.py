"""명시적으로 선택할 때만 실제 SDV 두 모델의 전체 흐름을 검증한다."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

from data_io import read_metadata

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("SYNTHETIC_MODEL_TESTS") == "1", "실제 모델 실행은 별도 선택")
class GenerationIntegrationTests(unittest.TestCase):
    """가상 원본·CPU·1 epoch로 네트워크를 차단한 생성 흐름을 확인한다."""

    def test_three_commands_with_real_models(self):
        """두 모델 학습부터 선택·Excel 저장·세 지표 평가까지 별도 프로세스로 실행한다."""
        with tempfile.TemporaryDirectory(prefix="synthetic-model-test-") as temporary:
            directory = Path(temporary)
            rng = np.random.default_rng(41)
            data = pd.DataFrame({
                "record_id": [f"R{i:06}" for i in range(120)],
                "display_name": ["SOURCE_ONLY_MARKER"] * 120,
                "address": ["ORIGINAL_ADDRESS_TOKEN"] * 120,
                "category": ["a", "b", "c"] * 40,
                "value_a": rng.normal(50, 8, 120),
                "value_b": rng.normal(20, 5, 120),
            })
            data.to_excel(directory / "original.xlsx", index=False)
            config = {
                "origin_path": "original.xlsx", "primary_key": "record_id",
                "column_types": {"value_a": "numerical", "value_b": "numerical"},
                "metadata_overrides": {
                    "record_id": {"sdtype": "id", "regex_format": "R[0-9]{6}"},
                    "display_name": {"sdtype": "name", "pii": True},
                    "address": {"sdtype": "address", "pii": True},
                    "category": {"sdtype": "categorical"},
                    "value_a": {"sdtype": "numerical"}, "value_b": {"sdtype": "numerical"},
                },
                "threshold": {"iterations": 4, "percentile": 90, "seed": 0},
                "generation": {"num_rows": 80, "epochs": 1, "seed": 7, "enable_gpu": False},
            }
            config_path = directory / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            environment = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
                           "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2"}
            # 로컬 학습 경로에서 예기치 않은 외부 연결이 있으면 테스트를 실패시킨다.
            code = (
                "import sys; from unittest.mock import patch; sys.path.insert(0, sys.argv[1]); "
                "from synthetic import main; "
                "guard = patch('socket.socket.connect', side_effect=AssertionError('NETWORK_BLOCKED')); "
                "guard.start(); raise SystemExit(main(sys.argv[2:]))"
            )
            for command in ("threshold", "generate", "evaluate"):
                completed = subprocess.run(
                    [sys.executable, "-B", "-c", code, str(ROOT), command, "--config", str(config_path)],
                    cwd=directory, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=180,
                )
                allowed = (0, 1) if command == "evaluate" else (0,)
                self.assertIn(completed.returncode, allowed, command + "\n" + completed.stdout + completed.stderr)
                self.assertNotIn("SOURCE_ONLY_MARKER", completed.stdout + completed.stderr)
                self.assertNotIn("ORIGINAL_ADDRESS_TOKEN", completed.stdout + completed.stderr)
            workbook = pd.read_excel(directory / "outputs/synthetic_data.xlsx", sheet_name=None)
            self.assertEqual(workbook["data"].shape, (80, 6))
            scores = workbook["model_scores"].set_index("모델")["품질 점수"].to_dict()
            self.assertEqual(set(scores), {"gaussian", "ctgan"})
            self.assertTrue(all(np.isfinite(score) for score in scores.values()))
            info = read_metadata(workbook["context"])
            expected = "gaussian" if scores["gaussian"] >= scores["ctgan"] else "ctgan"
            self.assertEqual(info["selected_model"], expected)
            self.assertEqual(info["generation"]["epochs"], 1)
            self.assertNotIn("SOURCE_ONLY_MARKER", workbook["data"]["display_name"].tolist())
            self.assertNotIn("ORIGINAL_ADDRESS_TOKEN", workbook["data"]["address"].tolist())
            evaluation = pd.read_excel(directory / "outputs/evaluation_results.xlsx", sheet_name="summary")
            self.assertEqual(len(evaluation), 3)
            self.assertFalse((evaluation["판정"] == "평가 불가").any())
            self.assertEqual(set(directory.iterdir()), {directory / "original.xlsx", config_path, directory / "outputs"})


if __name__ == "__main__":
    unittest.main()
