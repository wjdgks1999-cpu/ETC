"""분류 방식·모델 요청 계약·중단 후 행 단위 재개를 검증한다."""

from dataclasses import replace
import json
from unittest.mock import Mock, patch

import httpx

from config import SurveyError, load_settings
from labeling import InvalidResult, build_classifier, classify_file, parse_labels
from storage import read_table, write_workbook
from support import ROOT, SyntheticCase


class WorkflowTests(SyntheticCase):
    """실제 Excel 체크포인트와 모의 분류 함수를 연결해 업무 흐름을 확인한다."""

    def test_multi_labels_and_missing_auxiliary_values(self):
        """일반 복수 범주를 깨끗하게 저장하고 응답 외 결측 때문에 행을 버리지 않는다."""
        self.workbook([["001", "가상 첫 응답", None], [None, "가상 둘째", None], ["003", " ", None]],
                      headers=["id", "answer", "extra"])
        model = Mock(side_effect=[["홍보", "신규개방"], ["홍보"]])
        result = classify_file(self.input, self.output, self.settings, classifier=model)
        saved = read_table(self.output)
        self.assertEqual(result, {"completed": 2, "skipped": 1})
        self.assertEqual(saved.rows[0][-3:], ["홍보, 신규개방", "completed", None])
        self.assertEqual(saved.rows[1][0], None)
        self.assertEqual([row[-4] for row in saved.rows], [2, 3, 4])
        self.assertEqual(model.call_count, 2)

    def test_single_ai_category(self):
        """AI 응답은 단일 범주 형식으로 저장한다."""
        ai = replace(load_settings(ROOT / "config.ai.example.json"), answer_column="answer", id_column="id")
        self.workbook([[1, "가상 수요"]])
        classify_file(self.input, self.output, ai, classifier=Mock(return_value=[ai.categories[0]]))
        self.assertEqual(read_table(self.output).rows[0][-3], ai.categories[0])

    def test_failure_then_resume_only_unfinished_rows(self):
        """실패 앞의 결과를 보존하며 재개 시 실패·대기 행만 같은 원본 위치에서 처리한다."""
        self.workbook([[1, "first"], [2, "second"], [3, "third"]])
        first = Mock(side_effect=[["홍보"], RuntimeError("private text test-secret")])
        states = classify_file(self.input, self.output, self.settings, classifier=first)
        self.assertEqual(states, {"completed": 1, "error": 1, "pending": 1})
        self.assertEqual(read_table(self.output).rows[1][-3:], [None, "error", "API_ERROR"])
        second = Mock(side_effect=[["신규개방"], ["기타"]])
        states = classify_file(self.input, self.output, self.settings, classifier=second, resume=True)
        self.assertEqual(states, {"completed": 3})
        self.assertEqual([call.args[0] for call in second.call_args_list], ["second", "third"])
        self.assertEqual(read_table(self.output).rows[0][-3], "홍보")

    def test_interrupt_keeps_last_saved_row(self):
        """사용자 중단 시 마지막 완료 행을 유지하고 잠금을 해제한다."""
        self.workbook([[1, "first"], [2, "second"]])
        with self.assertRaises(KeyboardInterrupt):
            classify_file(self.input, self.output, self.settings,
                          classifier=Mock(side_effect=[["홍보"], KeyboardInterrupt()]))
        self.assertEqual([row[-2] for row in read_table(self.output).rows], ["completed", "pending"])
        self.assertFalse(self.output.with_suffix(".xlsx.lock").exists())

    def test_invalid_result_becomes_error_not_other(self):
        """빈 목록·미등록 범주·중복을 기타로 치환하지 않고 재개 가능한 오류로 남긴다."""
        self.workbook([[1, "가상 응답"]])
        for index, result in enumerate(([], ["미등록"], ["홍보", "홍보"], "홍보", None)):
            output = self.directory / f"result-{index}.xlsx"
            with self.subTest(result=result):
                classify_file(self.input, output, self.settings, classifier=Mock(return_value=result))
                self.assertEqual(read_table(output).rows[0][-3:], [None, "error", "INVALID_RESULT"])

    def test_ai_rejects_multiple_categories(self):
        """AI 단일 분류에 여러 범주가 들어오면 검증 오류로 처리한다."""
        ai = replace(load_settings(ROOT / "config.ai.example.json"), answer_column="answer", id_column="id")
        self.workbook([[1, "가상 응답"]])
        classify_file(self.input, self.output, ai, classifier=Mock(return_value=list(ai.categories[:2])))
        self.assertEqual(read_table(self.output).rows[0][-1], "INVALID_RESULT")

    def test_all_empty_needs_no_key_or_model(self):
        """응답이 전부 결측이면 API 키와 모델 생성 없이 모든 원본 행을 저장한다."""
        self.workbook([[1, None], [2, "  "]])
        with patch("labeling.build_classifier") as build:
            states = classify_file(self.input, self.output, self.settings)
        build.assert_not_called()
        self.assertEqual(states, {"skipped": 2})

    def test_complete_resume_needs_no_key_or_model(self):
        """완료된 작업 재개는 모델을 생성하거나 파일을 다시 저장하지 않는다."""
        self.workbook([[1, "가상"]])
        classify_file(self.input, self.output, self.settings, classifier=Mock(return_value=["홍보"]))
        before = self.output.read_bytes()
        with patch("labeling.build_classifier") as build:
            self.assertEqual(classify_file(self.input, self.output, self.settings, resume=True), {"completed": 1})
        build.assert_not_called()
        self.assertEqual(self.output.read_bytes(), before)

    def test_missing_key_does_not_create_output(self):
        """요청할 응답이 있는데 키가 없으면 결과 생성 전에 중단한다."""
        self.workbook([[1, "가상"]])
        with self.assertRaises(SurveyError):
            classify_file(self.input, self.output, self.settings)
        self.assertFalse(self.output.exists())

    def test_changed_settings_reject_resume_before_call(self):
        """질문·모델·프롬프트·모드 변경으로 기존 작업에 결과가 섞이지 않게 한다."""
        self.workbook([[1, "가상"]])
        classify_file(self.input, self.output, self.settings, classifier=Mock(side_effect=RuntimeError()))
        changes = [{"question": "새 질문"}, {"model": "different"}, {"prompt": self.settings.prompt + "\n"},
                   {"mode": "ai"}, {"timeout": 90}]
        model = Mock()
        before = self.output.read_bytes()
        for values in changes:
            with self.subTest(values=values), self.assertRaises(SurveyError):
                classify_file(self.input, self.output, replace(self.settings, **values),
                              classifier=model, resume=True)
        model.assert_not_called()
        self.assertEqual(self.output.read_bytes(), before)

    def test_changed_input_rejects_resume(self):
        """원본 내용이 바뀌면 같은 행 수·경로여도 재개하지 않는다."""
        self.workbook([[1, "가상"]])
        classify_file(self.input, self.output, self.settings, classifier=Mock(side_effect=RuntimeError()))
        write_workbook(self.input, {"responses": [["id", "answer"], [1, "수정된 가상"]]}, replace=True)
        model = Mock()
        with self.assertRaises(SurveyError):
            classify_file(self.input, self.output, self.settings, resume=True, classifier=model)
        model.assert_not_called()

    def test_checkpoint_row_change_rejects_resume(self):
        """체크포인트의 원본 응답이나 행 번호 수정은 재개 전에 감지한다."""
        self.workbook([[1, "가상"]])
        classify_file(self.input, self.output, self.settings, classifier=Mock(return_value=["홍보"]))
        table = read_table(self.output)
        meta = read_table(self.output, "run")
        table.rows[0][1] = "수정된 가상"
        write_workbook(self.output, {"responses": [table.headers] + table.rows,
                                    "run": [meta.headers] + meta.rows}, replace=True)
        with self.assertRaises(SurveyError):
            classify_file(self.input, self.output, self.settings, resume=True, classifier=Mock())

    def test_manual_category_correction_preserved_on_resume(self):
        """완료 행의 유효한 수동 분류값은 재개해도 다시 호출하거나 덮어쓰지 않는다."""
        self.workbook([[1, "first"], [2, "second"]])
        classify_file(self.input, self.output, self.settings,
                      classifier=Mock(side_effect=[["홍보"], RuntimeError()]))
        table = read_table(self.output)
        meta = read_table(self.output, "run")
        table.rows[0][-3] = "서비스 편의성"
        write_workbook(self.output, {"responses": [table.headers] + table.rows,
                                    "run": [meta.headers] + meta.rows}, replace=True)
        model = Mock(return_value=["기타"])
        classify_file(self.input, self.output, self.settings, resume=True, classifier=model)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(read_table(self.output).rows[0][-3], "서비스 편의성")

    def test_external_edit_during_request_not_overwritten(self):
        """모델 응답을 기다리는 동안 다른 작업이 결과를 수정하면 보존하고 멈춘다."""
        self.workbook([[1, "가상"]])

        def edit_external(answer):
            """실행 중 외부 파일 수정 상황을 모의한다."""
            self.output.write_bytes(b"external-edit")
            return ["홍보"]

        with self.assertRaises(SurveyError):
            classify_file(self.input, self.output, self.settings, classifier=edit_external)
        self.assertEqual(self.output.read_bytes(), b"external-edit")

    def test_output_errors_and_reserved_columns_before_request(self):
        """원본 경로 출력·기존 결과·입력 컬럼 충돌을 호출 전에 거부한다."""
        self.workbook([[1, "가상"]])
        model = Mock()
        with self.assertRaises(SurveyError):
            classify_file(self.input, self.input, self.settings, classifier=model)
        with self.assertRaises(SurveyError):
            classify_file(self.input, self.output, self.settings, classifier=model, resume=True)
        bad = self.directory / "reserved.xlsx"
        self.workbook([[1, "가상", None]], headers=["id", "answer", "category"], path=bad)
        with self.assertRaises(SurveyError):
            classify_file(bad, self.output, self.settings, classifier=model)
        model.assert_not_called()

    def test_initial_save_failure_prevents_api_request(self):
        """저장할 수 없는 출력에는 첫 모델 요청도 보내지 않는다."""
        self.workbook([[1, "가상"]])
        model = Mock()
        with patch("labeling.save_checkpoint", side_effect=OSError()), self.assertRaises(OSError):
            classify_file(self.input, self.output, self.settings, classifier=model)
        model.assert_not_called()

    def test_legacy_broken_serialization_not_silently_accepted(self):
        """기존 따옴표 오염값은 자동 추정 변환하지 않고 명시적으로 거부한다."""
        with self.assertRaises(InvalidResult):
            parse_labels("홍보', '신규개방", self.settings)


class ModelContractTests(SyntheticCase):
    """실제 LangChain·OpenAI SDK를 모의 HTTP 전송과 연결해 요청·파싱 계약을 검사한다."""

    def fake_response(self, request, payload):
        """요청된 도구 이름에 맞춘 가상 구조화 응답을 만든다."""
        body = json.loads(request.content)
        name = body["tools"][0]["function"]["name"]
        return httpx.Response(200, json={
            "id": "chatcmpl-test", "object": "chat.completion", "created": 0,
            "model": "gpt-4o-mini", "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{"id": "call-test", "type": "function",
                "function": {"name": name, "arguments": json.dumps(payload, ensure_ascii=False)}}]}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    def test_actual_chain_general_schema_and_prompt(self):
        """기본 모델·질문·응답·범주 열거와 복수 구조화 파싱을 실제 체인으로 확인한다."""
        requests = []

        def handler(request):
            """외부 전송 대신 요청을 기록하고 가상 복수 범주를 반환한다."""
            requests.append(request)
            return self.fake_response(request, {"categories": [{"category": "홍보"}, {"category": "신규개방"}]})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            classify = build_classifier(self.settings, "test-only-key", http_client=client)
            self.assertEqual(classify("가상 응답 {문자열}"), ["홍보", "신규개방"])
        body = json.loads(requests[0].content)
        self.assertEqual(len(requests), 1)
        self.assertEqual(body["model"], "gpt-4o-mini")
        self.assertEqual(body["messages"][0]["content"],
                         self.settings.prompt.format(question=self.settings.question, answer="가상 응답 {문자열}"))
        self.assertIn("enum", json.dumps(body["tools"]))
        self.assertEqual(requests[0].url.path, "/v1/chat/completions")
        self.assertEqual(requests[0].extensions["timeout"]["read"], 60)

    def test_actual_chain_ai_and_invalid_enum(self):
        """AI 단일 구조화 결과와 등록되지 않은 범주의 파싱 실패를 확인한다."""
        ai = load_settings(ROOT / "config.ai.example.json")

        def handler(request):
            """AI 단일 분류 응답을 가상으로 반환한다."""
            return self.fake_response(request, {"category": "기타"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            classify = build_classifier(ai, "test-only-key", http_client=client)
            self.assertEqual(classify("가상 응답"), ["기타"])

        def invalid(request):
            """미등록 범주를 반환해 로컬 검증을 확인한다."""
            return self.fake_response(request, {"category": "미등록"})

        with httpx.Client(transport=httpx.MockTransport(invalid)) as client:
            classify = build_classifier(ai, "test-only-key", http_client=client)
            with self.assertRaises(InvalidResult):
                classify("가상 응답")

    def test_rate_limit_no_automatic_retry(self):
        """429 오류를 자동 재전송하지 않고 행 오류로 저장한다."""
        calls = []

        def handler(request):
            """원문이 포함될 수 있는 가상 원격 오류를 반환한다."""
            calls.append(request)
            return httpx.Response(429, json={"error": {"message": "private remote text", "type": "rate_limit"}})

        self.workbook([[1, "가상 응답"]])
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            classify = build_classifier(self.settings, "test-only-key", http_client=client)
            states = classify_file(self.input, self.output, self.settings, classifier=classify)
        self.assertEqual(len(calls), 1)
        self.assertEqual(states, {"error": 1})
        self.assertEqual(read_table(self.output).rows[0][-1], "API_ERROR")

    def test_transport_timeout_preserves_pending_rows(self):
        """요청 시간 초과 시 이후 행을 요청하지 않고 대기 상태로 보존한다."""
        calls = []

        def handler(request):
            """가상 전송 계층에서 읽기 시간 초과를 발생시킨다."""
            calls.append(request)
            raise httpx.ReadTimeout("private timeout text", request=request)

        self.workbook([[1, "first"], [2, "second"]])
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            classify = build_classifier(self.settings, "test-only-key", http_client=client)
            states = classify_file(self.input, self.output, self.settings, classifier=classify)
        self.assertEqual(len(calls), 1)
        self.assertEqual(states, {"error": 1, "pending": 1})
