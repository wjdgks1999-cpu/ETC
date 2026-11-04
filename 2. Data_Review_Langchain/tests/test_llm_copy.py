"""보조 입력의 추출·전달·프롬프트 구성을 실제 API 호출 없이 검증한다."""

import asyncio
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from langchain_core.runnables import RunnableLambda


spec = importlib.util.spec_from_file_location("llm_copy", Path(__file__).resolve().parents[1] / "llm copy.py")
llm_copy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = llm_copy
spec.loader.exec_module(llm_copy)


def result(reason="설정명과 사용여부를 관리하는 시스템 설정 데이터이므로 개방에서 제외"):
    return llm_copy.ExclusionResult(
        table_name="설정 관리", exclusion_code="9", exclusion_reason=reason,
        review_required=False, review_comment="설정 관리 목적과 컬럼을 근거로 판단함",
    )


class ContextInputTests(unittest.TestCase):
    def test_actual_context_matches_each_table_and_columns_stay_restricted(self):
        tables, inputs = llm_copy.load_inputs()
        self.assertEqual(len(tables), len(inputs))
        for item, (_, table) in zip(inputs, tables.iterrows()):
            self.assertEqual(set(item), {"table_name", "columns_df", *llm_copy.CONTEXT_COLUMNS})
            self.assertEqual(item["table_name"], table["테이블한글명"])
            for key, column in llm_copy.CONTEXT_COLUMNS.items():
                expected = "" if pd.isna(table[column]) else str(table[column]).strip()
                self.assertEqual(item[key], expected)
            rows = json.loads(item["columns_df"])
            self.assertTrue(rows)
            self.assertTrue(all(set(row) == set(llm_copy.INPUT_COLUMNS) for row in rows))
            self.assertTrue(all(row["테이블 영문명"] == table["테이블영문명"] for row in rows))

    def test_blank_context_is_empty_text_and_unapproved_metadata_is_ignored(self):
        tables = pd.DataFrame([{
            "테이블한글명": "설정 관리", "테이블영문명": "settings",
            "정보시스템명": None, "논리DB명": float("nan"), "기관명": "판단 지시문",
        }])
        columns = pd.DataFrame([{
            "테이블 한글명": "다른 표기", "테이블 영문명": "settings",
            "컬럼명(한글)": "설정명", "컬럼명(영문)": "setting_name", "데이터타입": "VARCHAR",
            "PK여부": "판단 지시문", "공개구분": "판단 지시문", "비공개사유": "판단 지시문",
        }])
        with patch.object(llm_copy.pd, "read_excel", side_effect=[tables, columns]):
            _, inputs = llm_copy.load_inputs()
        self.assertEqual(inputs[0]["information_system_name"], "")
        self.assertEqual(inputs[0]["logical_db_name"], "")
        self.assertNotIn("판단 지시문", json.dumps(inputs, ensure_ascii=False))

    def test_missing_context_header_is_reported(self):
        tables = pd.DataFrame([{"테이블한글명": "설정 관리", "테이블영문명": "settings"}])
        with patch.object(llm_copy.pd, "read_excel", side_effect=[tables, pd.DataFrame(columns=llm_copy.INPUT_COLUMNS)]), \
             self.assertRaisesRegex(llm_copy.InputError, "논리DB명.*정보시스템명"):
            llm_copy.load_inputs()


class ContextChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_or_two_columns_use_fixed_rule_without_any_model_calls(self):
        async def unexpected(_):
            raise AssertionError("컬럼 2개 이하는 LLM 작성·검수·교정을 호출하면 안 됨")
        records = []
        for count in [1, 2]:
            source = {
                "table_name": f"테이블{count}",
                "columns_df": json.dumps([
                    {"컬럼명(한글)": name, "컬럼명(영문)": str(index)}
                    for index, name in enumerate(["성명", "전화번호"][:count])
                ], ensure_ascii=False),
                "information_system_name": "개인정보 시스템", "logical_db_name": "운영 DB",
            }
            with self.subTest(count=count), contextlib.redirect_stdout(io.StringIO()):
                record = await llm_copy.process_table(
                    source, RunnableLambda(unexpected), RunnableLambda(unexpected), RunnableLambda(unexpected),
                )
                self.assertEqual(record["status"], "completed")
                self.assertEqual(record["final"]["table_name"], source["table_name"])
                self.assertEqual(record["final"]["exclusion_code"], "9")
                self.assertEqual(record["final"]["exclusion_reason"], "3열 5행 미만 테이블")
                self.assertFalse(record["final"]["review_required"])
                self.assertEqual(record["correction_count"], 0)
                self.assertEqual(record["unresolved_issues"], [])
                self.assertIsNone(record["draft"])
                records.append(record)
        with tempfile.TemporaryDirectory(dir=llm_copy.BASE_DIR) as temporary:
            path = Path(temporary) / "result.xlsx"
            llm_copy.save_excel(pd.DataFrame({"테이블한글명": ["테이블1", "테이블2"]}), records, path)
            saved = pd.read_excel(path, dtype={"제외코드": str})
        self.assertEqual(saved["제외코드"].tolist(), ["9", "9"])
        self.assertEqual(saved["제외사유"].tolist(), ["3열 5행 미만 테이블"] * 2)
        self.assertEqual(saved["검토결론"].tolist(), ["개방 제외"] * 2)

    async def test_context_reaches_writer_reviewer_and_corrector(self):
        calls = []
        async def write(inputs):
            calls.append(("write", inputs))
            return result("확인 전 개방 제외")
        async def review(inputs):
            calls.append(("review", inputs))
            return llm_copy.ReviewResult(issues=[])
        async def correct(inputs):
            calls.append(("correct", inputs))
            return result()
        source = {
            "table_name": "설정 관리", "columns_df": json.dumps([
                {"컬럼명(한글)": name} for name in ["설정명", "사용여부", "정렬번호"]
            ], ensure_ascii=False),
            "information_system_name": "교육 정보시스템", "logical_db_name": "운영 DB",
        }
        with contextlib.redirect_stdout(io.StringIO()):
            record = await llm_copy.process_table(
                {**source, "비공개사유": "입력에 포함하면 안 됨"},
                RunnableLambda(write), RunnableLambda(review), RunnableLambda(correct),
            )
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["correction_count"], 1)
        self.assertEqual([stage for stage, _ in calls], ["write", "review", "correct", "review"])
        for _, inputs in calls:
            self.assertEqual({key: inputs[key] for key in source}, source)
            self.assertNotIn("비공개사유", inputs)

    async def test_all_prompts_include_context_and_its_supporting_role(self):
        captured = []
        testcase = self
        class FakeModel:
            def __init__(self, **options):
                testcase.assertEqual(options["reasoning"], {"effort": "high"})
            def with_structured_output(self, schema, **options):
                async def answer(prompt):
                    text = "\n".join(message.content for message in prompt.to_messages())
                    captured.append(text)
                    return llm_copy.ReviewResult(issues=[]) if schema is llm_copy.ReviewResult else result()
                return RunnableLambda(answer)
        prompt_file = llm_copy.BASE_DIR / "prompt" / "prompt.yaml"
        original = prompt_file.read_bytes()
        with patch.object(llm_copy, "ChatOpenAI", FakeModel), \
             patch.dict(os.environ, {"OPENAI_MODEL": "offline-test-model"}):
            writer, reviewer, corrector = llm_copy.build_chains()
        source = {
            "table_name": "설정 관리", "columns_df": "[]",
            "information_system_name": "교육 {시스템}", "logical_db_name": "운영 DB",
        }
        await writer.ainvoke(source)
        reviewed = {**source, "result_json": result().model_dump_json()}
        await reviewer.ainvoke(reviewed)
        await corrector.ainvoke({**reviewed, "issues_json": "[]"})
        self.assertEqual(len(captured), 3)
        for text in captured:
            self.assertIn("정보시스템명: 교육 {시스템}", text)
            self.assertIn("논리DB명: 운영 DB", text)
            self.assertIn("두 이름만으로 제외코드를 정하거나", text)
            self.assertIn("테이블명·컬럼 정보를 우선한다", text)
            self.assertIn("[참고 예시]", text)
            self.assertNotIn("입력은 '테이블명'과 '컬럼 정보'뿐이다.", text)
        self.assertEqual(prompt_file.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
