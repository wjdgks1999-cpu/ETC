"""모델 호출 없이 단계별 입력·판단 지침·구조화 응답 설정을 검증한다."""

import asyncio
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from helpers import ROOT, make_source, make_result
from metadata_review import prompts
from metadata_review.pipeline import process_table
from metadata_review.schemas import ExclusionResult, ReviewResult


class PromptTests(unittest.TestCase):
    """세 체인의 원본 입력과 보조 맥락 전달 방식을 확인한다."""

    def test_examples_and_context_reach_all_prompts(self):
        """참고 예시는 문자 그대로 포함하고 보조 맥락의 제한을 모든 단계에 전달하는지 확인한다."""
        source = make_source()
        source.update(result_json="{}", issues_json="[]")
        for index, prompt in enumerate(prompts.build_prompts(ROOT / "prompt")):
            text = "\n".join(message.content for message in prompt.invoke(source).to_messages())
            self.assertIn("[참고 예시]", text)
            self.assertIn('"table_name": "공휴일(대체휴일) 관리"', text)
            self.assertIn("예제 시스템", text)
            self.assertIn("예제 DB", text)
            self.assertIn("보조 입력", text)
            self.assertNotIn("{information_system_name}", text)
            if index == 1:
                self.assertNotIn("[출력 형식]", text)

    def test_strict_schema_and_model_options_are_preserved(self):
        """선택한 모델과 엄격한 작성·검수 결과 스키마가 체인에 적용되는지 확인한다."""
        options, schemas = [], []

        class FakeModel:
            """모델 생성과 결과 형식 요청만 기록하는 대체 객체다."""
            def __init__(self, **kwargs):
                """모델 설정을 기록한다."""
                options.append(kwargs)

            def with_structured_output(self, schema, **kwargs):
                """응답 형식을 기록하고 네트워크 없이 예제 응답을 제공한다."""
                schemas.append((schema, kwargs))
                return RunnableLambda(lambda _: ReviewResult(issues=[]) if schema is ReviewResult else make_result())

        with patch.object(prompts, "ChatOpenAI", FakeModel):
            chains = prompts.build_chains(ROOT / "prompt", "chosen-model")
        self.assertEqual(options[0]["model"], "chosen-model")
        self.assertTrue(options[0]["use_responses_api"])
        self.assertEqual(options[0]["reasoning"], {"effort": "high"})
        self.assertEqual([schema for schema, _ in schemas], [ExclusionResult, ReviewResult, ExclusionResult])
        self.assertTrue(all(args == {"method": "json_schema", "strict": True} for _, args in schemas))
        source = {**make_source(), "result_json": "{}", "issues_json": "[]"}
        for chain in chains:
            asyncio.run(chain.ainvoke(source))

    def test_context_reaches_writer_reviewer_and_corrector(self):
        """작성·검수·교정에 동일한 보조 정보가 전달되고 다른 메타데이터는 제외되는지 확인한다."""
        calls = []

        async def write(source):
            """교정이 필요한 초안을 만들어 작성 입력을 기록한다."""
            calls.append(source)
            return make_result(reason="확인 전 개방 제외")

        async def review(source):
            """검수 입력을 기록하고 형식 검증에 교정 여부를 맡긴다."""
            calls.append(source)
            return ReviewResult(issues=[])

        async def correct(source):
            """교정 입력을 기록하고 유효한 결과를 반환한다."""
            calls.append(source)
            return make_result()

        source = {**make_source(), "기관명": "전달하면 안 됨"}
        with contextlib.redirect_stdout(io.StringIO()):
            record = asyncio.run(process_table(source, RunnableLambda(write), RunnableLambda(review), RunnableLambda(correct)))
        self.assertEqual(record["status"], "completed")
        self.assertEqual(len(calls), 4)
        for item in calls:
            self.assertEqual(item["information_system_name"], source["information_system_name"])
            self.assertEqual(item["logical_db_name"], source["logical_db_name"])
            self.assertNotIn("기관명", item)
