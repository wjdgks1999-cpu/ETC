"""별도 프로세스 CLI 검증에서 실제 HTTP 요청만 모의 응답으로 교체한다."""

import os
from pathlib import Path
import sys
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from parse import main

REAL_CLIENT = httpx.AsyncClient


def fake_response(request):
    """시험용 정상·오류·누락 응답을 반환하며 외부에 접속하지 않는다."""
    mode = os.environ.get("PARSER_TEST_MODE", "success")
    if mode == "error":
        return httpx.Response(401, text="FAKE_PRIVATE_RESPONSE fake-key-for-cli")
    if mode == "empty":
        return httpx.Response(200, json={"elements": [], "usage": {"pages": 1}})
    pages = [1, 3] if mode == "review" else [1, 2]
    return httpx.Response(200, json={
        "model": "document-parse-fixture", "usage": {"pages": max(pages)},
        "elements": [{"page": page, "content": {"markdown": f"가상 페이지 {page}"}} for page in pages],
    })


def fake_client(*args, **kwargs):
    """명령의 HTTPX 클라이언트에 MockTransport를 주입한다."""
    kwargs["transport"] = httpx.MockTransport(fake_response)
    return REAL_CLIENT(*args, **kwargs)


if __name__ == "__main__":
    os.environ["UPSTAGE_API_KEY"] = "fake-key-for-cli"
    with patch("httpx.AsyncClient", side_effect=fake_client), patch(
        "httpx.AsyncHTTPTransport.handle_async_request", side_effect=AssertionError("REAL_NETWORK")
    ):
        raise SystemExit(main(sys.argv[1:]))
