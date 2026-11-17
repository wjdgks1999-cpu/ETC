"""가상 문서와 모의 HTTP 전송으로 요청 계약·오류·페이지 보존을 검증한다."""

import asyncio
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
from email import policy
from email.parser import BytesParser
import io
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from pypdf import PdfReader, PdfWriter

from client import group_pages, parse_document, read_source
from config import API_URL, ParseError, Settings


def payload(pages=(1,), count=1):
    """실제 문서 내용과 무관한 페이지 응답을 만든다."""
    return {"model": "document-parse-fixture", "usage": {"pages": count},
            "elements": [{"page": number, "content": {"markdown": f"가상 페이지 {number}"},
                          "coordinates": [{"x": 0.1, "y": 0.2}]} for number in pages]}


def multipart_parts(request):
    """전송 직전의 multipart 필드와 첨부 파일을 모의 요청에서 읽는다."""
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {request.headers['content-type']}\r\nMIME-Version: 1.0\r\n\r\n".encode()
        + request.read())
    return {part.get_param("name", header="content-disposition"): part for part in message.iter_parts()}


class ClientTests(unittest.IsolatedAsyncioTestCase):
    """요청은 MockTransport만 통과하도록 제한하고 모든 파일은 임시 경로에 둔다."""

    def setUp(self):
        """가상 HWPX 입력과 기본 옵션을 준비한다."""
        temporary = tempfile.TemporaryDirectory(prefix="document-client-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.input = self.directory / "example.hwpx"
        self.input.write_bytes(b"FAKE_HWPX_NOT_FOR_NETWORK")
        self.settings = Settings(self.input, self.directory / "output")
        self.network = patch("httpx.AsyncHTTPTransport.handle_async_request", side_effect=AssertionError("REAL_NETWORK"))
        self.network.start()
        self.addCleanup(self.network.stop)

    async def execute(self, handler, settings=None, path=None):
        """가상 전송기로 파싱을 실행한다."""
        return await parse_document(read_source(path or self.input), settings or self.settings,
                                    "fake-key-for-tests", transport=httpx.MockTransport(handler))

    def make_pdf(self, count=2, encrypted=False):
        """빈 페이지로 된 로컬 PDF 시험 자료를 만든다."""
        path = self.directory / "example.pdf"
        writer = PdfWriter()
        for _ in range(count):
            writer.add_blank_page(width=200, height=200)
        if encrypted:
            writer.encrypt("fake-test-password")
        writer.write(path)
        writer.close()
        return path

    async def test_hwpx_request_contract_and_content(self):
        """전체 HWPX와 기존 여섯 요청 옵션·인증 헤더를 그대로 전달한다."""
        requests = []
        response = payload()
        response["elements"] = [
            {"page": 1, "content": {"markdown": "| 항목 | 값 |\n|---|---|\n| 가상 | 1 |"}},
            {"page": 1, "content": {"markdown": "<table><tr><td>가상</td></tr></table>"}},
        ]

        def handler(request):
            """기존 로더의 실제 multipart 값과 새 요청을 대조한다."""
            requests.append(request)
            self.assertEqual(str(request.url), API_URL)
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.headers["authorization"], "Bearer fake-key-for-tests")
            fields = multipart_parts(request)
            expected = {"model": "document-parse", "ocr": "force", "output_formats": "['markdown']",
                        "chart_recognition": "True", "coordinates": "True", "base64_encoding": "[]"}
            for name, value in expected.items():
                self.assertEqual(fields[name].get_payload(decode=True).decode(), value)
            self.assertEqual(fields["document"].get_payload(decode=True), self.input.read_bytes())
            self.assertEqual(request.extensions["timeout"]["connect"], 15)
            return httpx.Response(200, json=response)

        result = await self.execute(handler)
        self.assertEqual(len(requests), 1)
        self.assertEqual(result.pages[0].content, " ".join(e["content"]["markdown"] for e in response["elements"]))
        self.assertEqual(result.pages[0].element_count, 2)
        self.assertEqual(result.issues, [])

    async def test_pdf_one_request_per_page_and_offset(self):
        """PDF의 요청별 한 페이지 분할과 원본 번호 복원을 유지한다."""
        requests = []

        def handler(request):
            """분할 파일이 실제 한 페이지 PDF인지 검사한다."""
            requests.append(request)
            content = multipart_parts(request)["document"].get_payload(decode=True)
            self.assertEqual(len(PdfReader(io.BytesIO(content)).pages), 1)
            return httpx.Response(200, json=payload())

        result = await self.execute(handler, path=self.make_pdf(3))
        self.assertEqual(len(requests), 3)
        self.assertEqual([page.number for page in result.pages], [1, 2, 3])
        self.assertEqual(result.total_pages, 3)

    async def test_sparse_page_numbers_are_not_renumbered(self):
        """5·9페이지를 1·2로 바꾸지 않고 누락 가능 범위를 기록한다."""
        result = await self.execute(lambda request: httpx.Response(200, json=payload((9, 5), 10)))
        self.assertEqual([page.number for page in result.pages], [5, 9])
        self.assertEqual(result.missing_pages, [1, 2, 3, 4, 6, 7, 8, 10])

    async def test_empty_pdf_page_keeps_missing_page_information(self):
        """추출 요소가 없는 PDF 페이지도 원본 전체 페이지 수에서 사라지지 않는다."""
        responses = [payload(), payload((), 1), payload()]
        result = await self.execute(lambda request: httpx.Response(200, json=responses.pop(0)), path=self.make_pdf(3))
        self.assertEqual([page.number for page in result.pages], [1, 3])
        self.assertEqual(result.missing_pages, [2])

    async def test_all_empty_results_fail(self):
        """빈 응답과 공백 내용만 있는 문서는 성공 결과가 아니다."""
        empty_text = payload()
        empty_text["elements"][0]["content"]["markdown"] = " \n"
        for response in (payload((), 1), empty_text):
            with self.subTest(response=response), self.assertRaises(ParseError):
                await self.execute(lambda request: httpx.Response(200, json=response))

    async def test_missing_page_count_is_reported_as_unknown(self):
        """응답에 전체 페이지 수가 없으면 관측 최댓값을 전체로 단정하지 않는다."""
        response = payload()
        response.pop("usage")
        response.pop("model")
        result = await self.execute(lambda request: httpx.Response(200, json=response))
        self.assertIsNone(result.total_pages)
        self.assertEqual({item["code"] for item in result.issues}, {"total_pages_unknown", "response_model_unknown"})

    async def test_http_errors_are_sanitized_and_not_retried(self):
        """인증·제한·서버 오류의 응답 원문을 노출하거나 자동 재전송하지 않는다."""
        for status in (401, 413, 429, 500):
            calls = []

            def handler(request):
                """가상 오류 본문을 반환하고 요청 수를 센다."""
                calls.append(request)
                return httpx.Response(status, text="FAKE_PRIVATE_RESPONSE fake-key-for-tests")

            with self.subTest(status=status), self.assertRaises(ParseError) as caught:
                await self.execute(handler)
            self.assertEqual(len(calls), 1)
            self.assertIn(str(status), str(caught.exception))
            self.assertNotIn("FAKE_PRIVATE_RESPONSE", str(caught.exception))
            self.assertNotIn("fake-key-for-tests", str(caught.exception))

    async def test_redirect_is_not_followed(self):
        """리다이렉트로 문서나 인증 정보가 다른 주소에 재전송되지 않는다."""
        calls = []

        def handler(request):
            """다른 주소를 가리키는 가상 리다이렉트를 반환한다."""
            calls.append(request)
            return httpx.Response(307, headers={"location": "https://example.invalid/other"})

        with self.assertRaises(ParseError):
            await self.execute(handler)
        self.assertEqual(len(calls), 1)

    async def test_http_timeout_is_sanitized(self):
        """HTTPX 제한 시간 오류의 상세 요청 정보가 출력되지 않는다."""
        def handler(request):
            """전송 계층의 시간 초과를 발생시킨다."""
            raise httpx.ReadTimeout("FAKE_PRIVATE_TIMEOUT", request=request)

        with self.assertRaises(ParseError) as caught:
            await self.execute(handler)
        self.assertNotIn("FAKE_PRIVATE_TIMEOUT", str(caught.exception))

    async def test_connection_failure_is_sanitized(self):
        """연결 실패의 URL·상세 내용을 안전한 오류로 바꾼다."""
        def handler(request):
            """가상 연결 실패를 발생시킨다."""
            raise httpx.ConnectError("FAKE_PRIVATE_CONNECTION", request=request)

        with self.assertRaises(ParseError) as caught:
            await self.execute(handler)
        self.assertNotIn("FAKE_PRIVATE_CONNECTION", str(caught.exception))

    async def test_overall_timeout_cancels_wait(self):
        """전체 요청 제한 시간에 도달하면 느린 응답을 취소한다."""
        cancelled = []

        async def handler(request):
            """긴 대기 중 취소 여부를 기록한다."""
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
            return httpx.Response(200, json=payload())

        with self.assertRaises(ParseError):
            await self.execute(handler, replace(self.settings, timeout=.05))
        self.assertEqual(cancelled, [True])

    async def test_invalid_json_and_elements_fail(self):
        """깨진 JSON과 누락된 요소 구조를 성공으로 처리하지 않는다."""
        for response in (httpx.Response(200, text="not-json"), httpx.Response(200, json={}),
                         httpx.Response(200, json={"elements": None})):
            with self.subTest(response=response), self.assertRaises(ParseError):
                await self.execute(lambda request: response)

    def test_invalid_element_contract(self):
        """잘못된 페이지·Markdown·좌표·총 페이지 수를 거부한다."""
        for page in (0, -1, True, "1", 101):
            response = payload()
            response["elements"][0]["page"] = page
            with self.subTest(page=page), self.assertRaises(ParseError):
                group_pages(response)
        for field, value in (("content", {}), ("coordinates", "bad")):
            response = payload()
            response["elements"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ParseError):
                group_pages(response)
        with self.assertRaises(ParseError):
            group_pages(payload((2,), 2), single_pdf_page=True)

    def test_corrupt_and_encrypted_pdf_fail_before_request(self):
        """읽을 수 없는 PDF는 외부 요청 전에 거부한다."""
        path = self.make_pdf(encrypted=True)
        with self.assertRaises(ParseError):
            read_source(path)
        path.write_bytes(b"%PDF-invalid")
        with self.assertRaises(ParseError):
            read_source(path)

    async def test_upload_size_limit_before_transport(self):
        """전송 한도를 넘는 문서는 가상 전송기로도 보내지 않는다."""
        source = read_source(self.input)
        with patch("client.MAX_UPLOAD_BYTES", 1):
            with self.assertRaises(ParseError):
                await parse_document(source, self.settings, "fake", transport=httpx.MockTransport(
                    lambda request: self.fail("전송되면 안 됨")))

    async def test_explicit_model_and_ocr_are_forwarded(self):
        """사용자가 지정한 모델·OCR 옵션이 요청과 결과 해석에 사용된다."""
        def handler(request):
            """명시적 요청 옵션을 확인한다."""
            parts = multipart_parts(request)
            self.assertEqual(parts["model"].get_payload(decode=True), b"document-parse-fixture")
            self.assertEqual(parts["ocr"].get_payload(decode=True), b"auto")
            return httpx.Response(200, json=payload())

        await self.execute(handler, replace(self.settings, model="document-parse-fixture", ocr="auto"))

    async def test_later_pdf_request_failure_leaves_no_output(self):
        """뒤쪽 PDF 요청이 실패하면 앞쪽 응답도 최종 폴더에 저장하지 않는다."""
        from parse import run

        calls = []
        path = self.make_pdf(3)

        def handler(request):
            """두 번째 요청에서 가상 서비스 오류를 반환한다."""
            calls.append(request)
            return httpx.Response(200, json=payload()) if len(calls) == 1 else httpx.Response(500)

        with self.assertRaises(ParseError), redirect_stdout(io.StringIO()):
            await run(replace(self.settings, input_path=path), transport=httpx.MockTransport(handler), api_key="fake")
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.settings.output_path.exists())

    async def test_pdf_warning_content_is_not_printed(self):
        """PDF 경고 본문은 숨기고 건수를 검토 항목에 남긴다."""
        path = self.make_pdf(1)
        reader = PdfReader(path)
        logger = logging.getLogger("pypdf")
        previous = (logger.handlers[:], logger.level, logger.propagate)

        def warn_and_return(stream):
            """문서 내부 문자열을 포함한 가상 경고를 발생시킨다."""
            logging.getLogger("pypdf._reader").warning("FAKE_PRIVATE_PDF_OBJECT")
            return reader

        captured = io.StringIO()
        with patch("client.PdfReader", side_effect=warn_and_return), redirect_stderr(captured):
            source = read_source(path)
        self.assertNotIn("FAKE_PRIVATE_PDF_OBJECT", captured.getvalue())
        self.assertEqual((logger.handlers, logger.level, logger.propagate), previous)
        result = await parse_document(source, self.settings, "fake", transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=payload())))
        self.assertIn({"code": "pdf_library_warnings", "count": 1}, result.issues)


if __name__ == "__main__":
    unittest.main()
