"""모델 대체 응답으로 병렬 처리·고정 규칙·중단 시 저장을 검증한다."""

import asyncio
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from langchain_core.runnables import RunnableLambda

from helpers import write_inputs, make_result
from metadata_review import workflow, prompts
from metadata_review.config import ReviewConfig
from metadata_review.rules import fixed_result
from metadata_review.schemas import InputError, ReviewResult
from metadata_review.pipeline import empty_record
from metadata_review.cli import main, parse_args


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    """입력에서 Excel 결과까지의 실행 흐름을 가상 데이터로 검증한다."""

    def setUp(self):
        """검증용 입력·출력 경로를 임시 폴더에 준비한다."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def settings(self, counts=(3,), **kwargs):
        """원하는 컬럼 수의 파일로 검토 실행 설정을 만든다."""
        tables, columns = write_inputs(self.root, counts)
        return ReviewConfig(tables=tables, columns=columns, output=self.root / "result.xlsx",
                            env_file=self.root / "missing.env", **kwargs)

    async def test_small_tables_require_no_model_or_credentials(self):
        """1·2개 컬럼에는 API 없이 합의한 코드와 사유가 그대로 적용되는지 확인한다."""
        cfg = self.settings((1, 2))
        with patch.dict(os.environ, {}, clear=True), patch.object(workflow, "load_dotenv") as env, patch.object(prompts, "build_chains") as chains, contextlib.redirect_stdout(io.StringIO()):
            outcome = await workflow.run_review(cfg)
        env.assert_not_called()
        chains.assert_not_called()
        saved = pd.read_excel(outcome.output, dtype={"제외코드": str})
        self.assertEqual(saved["제외코드"].tolist(), ["9", "9"])
        self.assertEqual(saved["제외사유"].tolist(), ["3열 5행 미만 테이블"] * 2)
        self.assertEqual(saved["교정횟수"].tolist(), [0, 0])
        self.assertEqual(outcome.exit_code, 0)
        self.assertIsNone(fixed_result("예제", 3))

    async def test_concurrency_order_and_failed_draft_preservation(self):
        """병렬 수 제한과 원본 순서, 실패한 초안의 보존을 함께 확인한다."""
        cfg = self.settings((3,) * 6, max_concurrency=2)
        active = peak = 0
        order = []

        async def write(source):
            """완료 시간을 다르게 하여 동시 처리 수와 완료 순서를 관찰한다."""
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.04 if source["table_name"].endswith("0") else 0.001)
                return make_result(source["table_name"])
            finally:
                active -= 1

        async def review(source):
            """한 테이블의 검수만 실패시켜 부분 실패를 재현한다."""
            order.append(source["table_name"])
            if source["table_name"].endswith("2"):
                raise RuntimeError("private-error-marker")
            return ReviewResult(issues=[])

        chains = (RunnableLambda(write), RunnableLambda(review), RunnableLambda(lambda _: make_result()))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "offline", "OPENAI_MODEL": "offline"}), patch.object(workflow, "load_dotenv"), patch.object(prompts, "build_chains", return_value=chains), contextlib.redirect_stdout(io.StringIO()):
            outcome = await workflow.run_review(cfg)
        self.assertEqual(peak, 2)
        self.assertFalse(order[0].endswith("0"))
        self.assertEqual(outcome.counts, {"completed": 5, "failed": 1})
        self.assertEqual(outcome.exit_code, 1)
        saved = pd.read_excel(outcome.output)
        self.assertEqual(saved["테이블한글명"].tolist(), [f"예제 테이블 {i}" for i in range(6)])
        self.assertEqual(saved.loc[2, "처리상태"], "failed")
        self.assertTrue(pd.isna(saved.loc[2, "제외사유"]))
        self.assertTrue(pd.notna(saved.loc[2, "초안제외사유"]))
        self.assertNotIn("private-error-marker", str(outcome.records))

    async def test_cancellation_saves_completed_and_pending_rows(self):
        """중단 시 완료분을 저장하고 나머지는 미처리로 남기며 대기 작업을 정리하는지 확인한다."""
        cfg = self.settings((3, 3), max_concurrency=2)
        completed = asyncio.Event()

        async def process(source, *_):
            """첫 테이블만 완료하고 다음 작업은 중단될 때까지 대기한다."""
            if source["table_name"].endswith("0"):
                record = empty_record(source["table_name"])
                record.update(status="completed", final=make_result(source["table_name"]).model_dump())
                completed.set()
                return record
            await asyncio.Event().wait()

        with patch.dict(os.environ, {"OPENAI_API_KEY": "offline", "OPENAI_MODEL": "offline"}), patch.object(workflow, "load_dotenv"), patch.object(prompts, "build_chains", return_value=(None,) * 3), patch.object(workflow, "process_table", side_effect=process), contextlib.redirect_stdout(io.StringIO()):
            task = asyncio.create_task(workflow.run_review(cfg))
            await asyncio.wait_for(completed.wait(), timeout=3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        saved = pd.read_excel(cfg.output)
        self.assertEqual(saved["처리상태"].tolist(), ["completed", "not_processed"])

    async def test_model_settings_required_only_for_model_work(self):
        """모델 처리가 필요한 입력은 키·모델 설정 없이는 호출을 시작하지 않는지 확인한다."""
        cfg = self.settings()
        with patch.dict(os.environ, {}, clear=True), patch.object(workflow, "load_dotenv"), patch.object(prompts, "build_chains") as chains:
            with self.assertRaisesRegex(InputError, "OPENAI_API_KEY"):
                await workflow.run_review(cfg)
            with patch.dict(os.environ, {"OPENAI_API_KEY": "offline"}):
                with self.assertRaisesRegex(InputError, "OPENAI_MODEL"):
                    await workflow.run_review(cfg)
        chains.assert_not_called()

    async def test_existing_output_is_preserved(self):
        """교체 허용 없이 같은 결과 파일이 있으면 모델 호출 전에 중단하는지 확인한다."""
        cfg = self.settings((1,))
        cfg.output.write_bytes(b"keep")
        with self.assertRaises(InputError):
            await workflow.run_review(cfg)
        self.assertEqual(cfg.output.read_bytes(), b"keep")


class CommandTests(unittest.TestCase):
    """통합 명령의 옵션 검증과 외부 호출 없는 고정 규칙 실행을 확인한다."""

    def test_invalid_limits_and_source_output_are_rejected(self):
        """잘못된 실행 범위와 원본 경로 출력 설정을 거부하는지 확인한다."""
        for args in (("--limit", "0"), ("--max-concurrency", "0"), ("--output", "a.csv"), ("--tables", "same.xlsx", "--output", "same.xlsx")):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parse_args(["run", *args])

    def test_compare_and_fixed_run_commands(self):
        """같은 가상 입력으로 비교와 고정 규칙 검토 명령을 실제 실행한다."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tables, columns = write_inputs(root, (1, 2))
            common = ["--tables", str(tables), "--columns", str(columns)]
            with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["compare", *common, "--output", str(root / "compare.csv")]), 0)
                self.assertEqual(main(["run", *common, "--output", str(root / "review.xlsx")]), 0)
            self.assertTrue((root / "compare.csv").exists())
            self.assertTrue((root / "review.xlsx").exists())
