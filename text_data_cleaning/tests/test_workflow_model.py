"""정제 흐름·체크포인트·모델 요청 계약을 가상 데이터로 검증한다."""

from dataclasses import replace
import json
from unittest.mock import Mock, patch

import httpx

from config import CleaningError, load_settings
from model import InvalidResult, build_cleaner, build_schema
from storage import PROCESSING_HEADERS, load_checkpoint, read_input, write_workbook
from workflow import clean_file
from support import SyntheticCase


def rewrite_checkpoint(path, checkpoint):
    """가상 체크포인트를 수정해 무결성 검증 상황을 만든다."""
    return write_workbook(path, {
        "data": [checkpoint.headers] + checkpoint.rows,
        "processing": [PROCESSING_HEADERS] + checkpoint.processing,
        "run": [["key", "value"]] + [[key, json.dumps(value, ensure_ascii=False)]
                                      for key, value in checkpoint.metadata.items()],
    }, replace=True)


class WorkflowTests(SyntheticCase):
    """실제 파일 저장과 대체 모델을 연결해 상태별 처리 차이를 확인한다."""

    def test_cleaning_preserves_input_other_columns_and_row_identity(self):
        """대상 본문만 바꾸고 원본 파일·식별자·다른 컬럼·빈 행을 보존한다."""
        path = self.csv_file([["001", "<p>가상</p>", "NA"], ["002", "", ""]],
                             headers=["id", "body", "extra"])
        before = path.read_bytes()
        cleaner = Mock(return_value="가상")
        states = clean_file(path, self.output, self.settings, cleaner=cleaner)
        saved = load_checkpoint(self.output)
        self.assertEqual(states, {"completed": 1, "skipped": 1})
        self.assertEqual(saved.rows, [["001", "가상", "NA"], ["002", None, None]])
        self.assertEqual([record[0] for record in saved.processing], [2, 3])
        self.assertEqual(path.read_bytes(), before)
        cleaner.assert_called_once_with("<p>가상</p>")

    def test_html_output_connects_to_privacy_without_metadata_columns(self):
        """HTML 정제의 data 시트를 개인정보 정제 입력으로 직접 연결한다."""
        self.workbook([["001", "<p>가상 내용 FAKE-PERSON</p>"], ["002", None]])
        clean_file(self.input, self.output, self.settings, cleaner=Mock(return_value="가상 내용 FAKE-PERSON"))
        second = self.directory / "privacy.xlsx"
        privacy = replace(load_settings("privacy"), column="body")
        cleaner = Mock(return_value="가상 내용")
        states = clean_file(self.output, second, privacy, cleaner=cleaner)
        result = load_checkpoint(second)
        self.assertEqual(states, {"completed": 1, "skipped": 1})
        self.assertEqual(result.headers, ["id", "body"])
        self.assertEqual(result.rows[0], ["001", "가상 내용"])
        self.assertEqual([row[0] for row in result.processing], [2, 3])
        cleaner.assert_called_once_with("가상 내용 FAKE-PERSON")

    def test_failure_preserves_unprocessed_content_and_resume_skips_completed(self):
        """첫 실패를 기록하고 완료 행을 다시 호출하지 않으며 나머지 원문을 유지한다."""
        self.workbook([[1, "first"], [2, "second"], [3, "third"]])
        first = Mock(side_effect=["clean-first", RuntimeError("PRIVATE_RESPONSE test-secret")])
        states = clean_file(self.input, self.output, self.settings, cleaner=first)
        saved = load_checkpoint(self.output)
        self.assertEqual(states, {"completed": 1, "error": 1, "pending": 1})
        self.assertEqual(saved.rows, [[1, "clean-first"], [2, "second"], [3, "third"]])
        self.assertEqual(saved.processing[1], [3, "error", None, "API_ERROR"])
        second = Mock(side_effect=["clean-second", "clean-third"])
        states = clean_file(self.input, self.output, self.settings, cleaner=second, resume=True)
        self.assertEqual(states, {"completed": 3})
        self.assertEqual([call.args[0] for call in second.call_args_list], ["second", "third"])
        self.assertEqual(load_checkpoint(self.output).rows[0][1], "clean-first")

    def test_null_wrong_type_and_unsavable_results_leave_original(self):
        """잘못된 결과가 원문을 빈 값으로 덮어쓰지 않도록 오류로 기록한다."""
        self.workbook([[1, "original"]])
        for index, value in enumerate((None, 1, {}, ["text"], "x" * 32768, "bad\x00text", "\ud800")):
            output = self.directory / f"invalid-{index}.xlsx"
            with self.subTest(index=index):
                clean_file(self.input, output, self.settings, cleaner=Mock(return_value=value))
                saved = load_checkpoint(output)
                self.assertEqual(saved.rows[0][1], "original")
                self.assertEqual(saved.processing[0][1:], ["error", None, "INVALID_RESULT"])

    def test_empty_results_require_review_and_do_not_repeat_on_resume(self):
        """정상 문자열이지만 빈 결과는 오류와 구분하며 재개 시 자동 재호출하지 않는다."""
        self.workbook([[1, "first"], [2, "second"]])
        states = clean_file(self.input, self.output, self.settings, cleaner=Mock(side_effect=["", "  "]))
        self.assertEqual(states, {"review_required": 2})
        saved = load_checkpoint(self.output)
        self.assertEqual(saved.processing[0][2:], ["", "EMPTY_RESULT"])
        before = self.output.read_bytes()
        with patch("workflow.build_cleaner") as build:
            self.assertEqual(clean_file(self.input, self.output, self.settings, resume=True), states)
        build.assert_not_called()
        self.assertEqual(self.output.read_bytes(), before)

    def test_unfinished_or_review_output_cannot_enter_next_stage(self):
        """오류·대기·빈 결과 검토가 남은 정제 파일의 자동 단계 연결을 차단한다."""
        self.workbook([[1, "first"], [2, "second"]])
        for index, values in enumerate(([RuntimeError()], ["", "clean-second"])):
            output = self.directory / f"partial-{index}.xlsx"
            clean_file(self.input, output, self.settings, cleaner=Mock(side_effect=values))
            next_cleaner = Mock()
            with self.subTest(index=index), self.assertRaises(CleaningError):
                clean_file(output, self.directory / f"next-{index}.xlsx",
                           replace(self.settings, mode="privacy"), cleaner=next_cleaner)
            next_cleaner.assert_not_called()

    def test_interrupt_keeps_last_saved_row_and_releases_lock(self):
        """사용자 중단 후 완료 행을 보존하고 대기 행에서 재개할 수 있게 한다."""
        self.workbook([[1, "first"], [2, "second"]])
        with self.assertRaises(KeyboardInterrupt):
            clean_file(self.input, self.output, self.settings,
                       cleaner=Mock(side_effect=["clean-first", KeyboardInterrupt()]))
        self.assertEqual([row[1] for row in load_checkpoint(self.output).processing], ["completed", "pending"])
        self.assertFalse(self.output.with_name(self.output.name + ".lock").exists())

    def test_blank_and_zero_row_inputs_require_no_key(self):
        """빈 본문과 헤더뿐인 파일은 키나 모델 생성 없이 저장한다."""
        for index, rows in enumerate(([[1, None], [2, "  "]], [])):
            path = self.workbook(rows, path=self.directory / f"blank-{index}.xlsx")
            output = self.directory / f"blank-result-{index}.xlsx"
            with patch("workflow.build_cleaner") as build:
                states = clean_file(path, output, self.settings)
            build.assert_not_called()
            self.assertEqual(states, {"skipped": 2} if rows else {})

    def test_completed_resume_requires_no_key_and_no_write(self):
        """완료된 작업 재개는 모델 생성과 파일 재저장을 하지 않는다."""
        self.workbook([[1, "first"]])
        clean_file(self.input, self.output, self.settings, cleaner=Mock(return_value="clean"))
        before = self.output.read_bytes()
        with patch("workflow.build_cleaner") as build:
            self.assertEqual(clean_file(self.input, self.output, self.settings, resume=True), {"completed": 1})
        build.assert_not_called()
        self.assertEqual(self.output.read_bytes(), before)

    def test_missing_key_or_bad_target_creates_no_output(self):
        """키 누락·본문 컬럼 오류·비문자열 본문은 요청 또는 결과 생성 전에 실패한다."""
        self.workbook([[1, "first"]])
        with self.assertRaises(CleaningError):
            clean_file(self.input, self.output, self.settings)
        with self.assertRaises(CleaningError):
            clean_file(self.input, self.output, replace(self.settings, column="missing"), cleaner=Mock())
        numeric = self.workbook([[1, 123]], path=self.directory / "numeric.xlsx")
        cleaner = Mock()
        with self.assertRaises(CleaningError):
            clean_file(numeric, self.output, self.settings, cleaner=cleaner)
        cleaner.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_original_existing_and_missing_resume_paths_rejected(self):
        """원본 경로·기존 결과 덮어쓰기와 없는 결과 재개를 요청 전에 막는다."""
        self.workbook([[1, "first"]])
        cleaner = Mock()
        with self.assertRaises(CleaningError):
            clean_file(self.input, self.input, self.settings, cleaner=cleaner)
        with self.assertRaises(CleaningError):
            clean_file(self.input, self.output, self.settings, cleaner=cleaner, resume=True)
        self.output.write_bytes(b"existing")
        with self.assertRaises(CleaningError):
            clean_file(self.input, self.output, self.settings, cleaner=cleaner)
        cleaner.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b"existing")

    def test_changed_source_or_settings_reject_resume(self):
        """원본·모드·모델·프롬프트·입력 해석이 바뀌면 기존 작업에 섞지 않는다."""
        self.workbook([[1, "first"]])
        clean_file(self.input, self.output, self.settings, cleaner=Mock(side_effect=RuntimeError()))
        cleaner = Mock()
        before = self.output.read_bytes()
        for changes in ({"mode": "privacy"}, {"model": "other"}, {"prompt": "다른 지시"},
                        {"encoding": "utf-8"}, {"timeout": 90}):
            with self.subTest(changes=changes), self.assertRaises(CleaningError):
                clean_file(self.input, self.output, replace(self.settings, **changes), cleaner=cleaner, resume=True)
        write_workbook(self.input, {"data": [["id", "body"], [1, "different"]]}, replace=True)
        with self.assertRaises(CleaningError):
            clean_file(self.input, self.output, self.settings, cleaner=cleaner, resume=True)
        cleaner.assert_not_called()
        self.assertEqual(self.output.read_bytes(), before)

    def test_checkpoint_data_tampering_detected_before_request(self):
        """저장된 다른 컬럼의 수정도 원본과 비교해 재개 전에 발견한다."""
        self.workbook([["001", "first"]])
        clean_file(self.input, self.output, self.settings, cleaner=Mock(side_effect=RuntimeError()))
        checkpoint = load_checkpoint(self.output)
        checkpoint.rows[0][0] = "changed-id"
        rewrite_checkpoint(self.output, checkpoint)
        cleaner = Mock()
        with self.assertRaises(CleaningError):
            clean_file(self.input, self.output, self.settings, cleaner=cleaner, resume=True)
        cleaner.assert_not_called()

    def test_checkpoint_state_and_row_tampering_rejected(self):
        """잘못된 상태 조합과 원본 행 번호 변경을 조용히 수용하지 않는다."""
        self.workbook([[1, "first"]])
        clean_file(self.input, self.output, self.settings, cleaner=Mock(return_value="clean"))
        checkpoint = load_checkpoint(self.output)
        checkpoint.processing[0][0] = 999
        rewrite_checkpoint(self.output, checkpoint)
        with self.assertRaises(CleaningError):
            clean_file(self.input, self.output, self.settings, resume=True, cleaner=Mock())
        checkpoint.processing[0][1] = "pending"
        rewrite_checkpoint(self.output, checkpoint)
        with self.assertRaises(CleaningError):
            load_checkpoint(self.output)

    def test_external_edit_while_waiting_is_not_overwritten(self):
        """모델 응답을 기다리는 동안 생긴 다른 작업의 변경을 보존한다."""
        self.workbook([[1, "first"]])

        def edit(contents):
            """정제 요청 중 외부 수정이 발생한 상황을 모의한다."""
            self.output.write_bytes(b"external-edit")
            return "clean"

        with self.assertRaises(CleaningError):
            clean_file(self.input, self.output, self.settings, cleaner=edit)
        self.assertEqual(self.output.read_bytes(), b"external-edit")

    def test_initial_save_failure_prevents_requests(self):
        """초기 체크포인트를 저장하지 못하면 모델에 본문을 보내지 않는다."""
        self.workbook([[1, "first"]])
        cleaner = Mock()
        with patch("workflow.save_checkpoint", side_effect=OSError()), self.assertRaises(OSError):
            clean_file(self.input, self.output, self.settings, cleaner=cleaner)
        cleaner.assert_not_called()

    def test_mid_save_failure_preserves_previous_checkpoint(self):
        """처리 후 파일 교체가 실패하면 이전 체크포인트와 원본 내용을 보존한다."""
        self.workbook([[1, "first"]])
        with patch("storage.os.replace", side_effect=OSError()), self.assertRaises(OSError):
            clean_file(self.input, self.output, self.settings, cleaner=Mock(return_value="clean"))
        saved = load_checkpoint(self.output)
        self.assertEqual(saved.rows[0][1], "first")
        self.assertEqual(saved.processing[0][1], "pending")


class ModelTests(SyntheticCase):
    """실제 LangChain과 SDK를 모의 HTTP로 연결해 요청·파싱·오류 처리를 확인한다."""

    def response(self, request, payload):
        """요청한 도구 이름에 대응하는 가상 구조화 응답을 만든다."""
        name = json.loads(request.content)["tools"][0]["function"]["name"]
        return httpx.Response(200, json={
            "id": "chatcmpl-test", "object": "chat.completion", "created": 0,
            "model": "gpt-5.6-luna", "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{"id": "call-test", "type": "function",
                "function": {"name": name, "arguments": json.dumps(payload)}}]}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    def test_request_preserves_model_and_separates_body_role(self):
        """기본 모델·요청 제한과 system 지시·user 본문 분리를 실제 요청에서 확인한다."""
        requests = []
        settings = replace(self.settings, prompt=self.settings.prompt + "\n{literal}")

        def handler(request):
            """가상 응답을 반환하며 외부로 전송하지 않는다."""
            requests.append(request)
            return self.response(request, {"content": "clean text"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            cleaner = build_cleaner(settings, "test-only-key", http_client=client)
            self.assertEqual(cleaner("<p>{literal body}</p>"), "clean text")
        body = json.loads(requests[0].content)
        self.assertEqual(body["model"], "gpt-5.6-luna")
        self.assertEqual(body["messages"], [{"role": "system", "content": settings.prompt},
                                             {"role": "user", "content": "<p>{literal body}</p>"}])
        self.assertEqual(requests[0].extensions["timeout"]["read"], 60)
        self.assertEqual(requests[0].url.path, "/v1/chat/completions")

    def test_required_string_schema_rejects_old_loss_cases(self):
        """두 출력 모델 모두 누락·null·다른 키·추가 키를 거부하고 빈 문자열은 구분 가능하게 받는다."""
        from pydantic import ValidationError

        for mode in ("html", "privacy"):
            schema, field = build_schema(mode)
            wrong = "Preprocess_Content" if mode == "html" else "content"
            for payload in ({}, {field: None}, {wrong: "text"}, {field: 3}, {field: "text", "extra": 1}):
                with self.subTest(mode=mode, payload=payload), self.assertRaises(ValidationError):
                    schema.model_validate(payload)
            self.assertEqual(getattr(schema.model_validate({field: ""}), field), "")

    def test_privacy_chain_and_invalid_field(self):
        """개인정보 정제 필드를 유지하며 잘못된 필드명은 실제 체인에서도 실패한다."""
        settings = load_settings("privacy")

        def handler(request):
            """개인정보 정제의 가상 구조화 응답을 반환한다."""
            return self.response(request, {"Preprocess_Content": "clean text"})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            self.assertEqual(build_cleaner(settings, "test-only-key", http_client=client)("fake"), "clean text")

        def invalid(request):
            """다른 작업의 필드가 반환되는 오류를 모의한다."""
            return self.response(request, {"content": "unexpected"})

        with httpx.Client(transport=httpx.MockTransport(invalid)) as client:
            with self.assertRaises(InvalidResult):
                build_cleaner(settings, "test-only-key", http_client=client)("fake")

    def test_rate_limit_no_retry_and_no_remote_error_in_output(self):
        """429 응답을 자동 재전송하지 않고 고정 오류 코드만 저장한다."""
        requests = []

        def handler(request):
            """본문을 포함할 수 있는 가상 원격 오류를 반환한다."""
            requests.append(request)
            return httpx.Response(429, json={"error": {"message": "PRIVATE_RESPONSE test-secret", "type": "rate_limit"}})

        self.workbook([[1, "original"]])
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            cleaner = build_cleaner(self.settings, "test-only-key", http_client=client)
            self.assertEqual(clean_file(self.input, self.output, self.settings, cleaner=cleaner), {"error": 1})
        self.assertEqual(len(requests), 1)
        self.assertEqual(load_checkpoint(self.output).processing[0][3], "API_ERROR")

    def test_timeout_does_not_advance_to_next_row(self):
        """요청 시간 초과 시 해당 행을 오류로 남기고 다음 행 호출을 멈춘다."""
        requests = []

        def handler(request):
            """읽기 시간 초과를 가상 전송 계층에서 발생시킨다."""
            requests.append(request)
            raise httpx.ReadTimeout("synthetic timeout", request=request)

        self.workbook([[1, "first"], [2, "second"]])
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            cleaner = build_cleaner(self.settings, "test-only-key", http_client=client)
            self.assertEqual(clean_file(self.input, self.output, self.settings, cleaner=cleaner), {"error": 1, "pending": 1})
        self.assertEqual(len(requests), 1)
