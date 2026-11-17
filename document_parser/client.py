"""Upstage 요청과 페이지별 응답 변환을 담당하며 문서를 출력하지 않는다."""

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import io
import logging
import mimetypes

import httpx
from pypdf import PdfReader, PdfWriter

from config import API_URL, MAX_UPLOAD_BYTES, ParseError


@dataclass
class Source:
    """읽은 원본 스냅샷과 식별 정보·PDF 구조를 보관한다."""

    name: str
    content: bytes = field(repr=False)
    sha256: str
    pdf: PdfReader | None = field(default=None, repr=False)
    pdf_warning_count: int = 0


@dataclass
class Page:
    """원본 페이지 번호와 파싱된 내용·요소 수·좌표를 보관한다."""

    number: int
    content: str = field(repr=False)
    element_count: int
    coordinates: list = field(default_factory=list, repr=False)


@dataclass
class ParseResult:
    """페이지 결과와 검토에 필요한 요청·응답 요약을 보관한다."""

    pages: list[Page]
    total_pages: int | None
    request_count: int
    response_models: list[str]
    missing_pages: list[int]
    issues: list[dict]


class PdfLogCounter(logging.Handler):
    """PDF 경고의 본문을 보관하거나 출력하지 않고 발생 건수만 센다."""

    def __init__(self):
        """경고 이상 로그를 집계할 핸들러를 초기화한다."""
        super().__init__(logging.WARNING)
        self.count = 0

    def emit(self, record):
        """로그 메시지 대신 건수만 누적한다."""
        self.count += 1


@contextmanager
def capture_pdf_logs():
    """짧은 동기 PDF 처리 구간의 로그를 집계한 뒤 기존 로깅 설정을 복원한다."""
    logger = logging.getLogger("pypdf")
    handlers, level, propagate = logger.handlers[:], logger.level, logger.propagate
    counter = PdfLogCounter()
    logger.handlers = [counter]
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    try:
        yield counter
    finally:
        logger.handlers = handlers
        logger.setLevel(level)
        logger.propagate = propagate
        counter.close()


def read_source(path):
    """원본을 한 번 읽어 해시를 만들고 PDF이면 요청 전에 구조를 검사한다."""
    try:
        content = path.read_bytes()
    except OSError as error:
        raise ParseError("입력 파일을 읽을 수 없습니다.") from error
    if not content:
        raise ParseError("입력 파일이 비어 있습니다.")
    reader, warning_count = None, 0
    if path.suffix.lower() == ".pdf" or content.lstrip().startswith(b"%PDF-"):
        try:
            with capture_pdf_logs() as counter:
                reader = PdfReader(io.BytesIO(content))
                if reader.is_encrypted and not reader.decrypt(""):
                    raise ParseError("암호를 해제한 PDF를 입력하세요.")
                if not reader.pages:
                    raise ParseError("PDF에 페이지가 없습니다.")
                warning_count = counter.count
        except ParseError:
            raise
        except Exception as error:
            raise ParseError("PDF 구조를 읽을 수 없습니다.") from error
    elif len(content) > MAX_UPLOAD_BYTES:
        raise ParseError("PDF 이외 문서는 동기 API의 100MB 요청 한도를 넘길 수 없습니다.")
    return Source(path.name, content, hashlib.sha256(content).hexdigest(), reader, warning_count)


def request_parts(source):
    """PDF는 기존처럼 한 페이지씩, 나머지 문서는 전체를 전송할 준비를 한다."""
    if source.pdf is None:
        yield source.name, source.content, 0
        return
    for offset in range(len(source.pdf.pages)):
        with capture_pdf_logs() as counter:
            writer = PdfWriter()
            try:
                writer.add_page(source.pdf.pages[offset])
                with io.BytesIO() as buffer:
                    writer.write(buffer)
                    content = buffer.getvalue()
            finally:
                writer.close()
            source.pdf_warning_count += counter.count
        yield f"page_{offset + 1}.pdf", content, offset


def request_options(settings):
    """기존 로더와 같은 모델·OCR·출력·좌표·차트 옵션을 만든다."""
    return {"model": settings.model, "ocr": settings.ocr, "output_formats": "['markdown']",
            "chart_recognition": "True", "coordinates": "True", "base64_encoding": "[]"}


async def send_request(client, settings, filename, content):
    """한 문서를 자동 재시도 없이 전송하고 안전한 오류와 JSON 응답을 반환한다."""
    if len(content) > MAX_UPLOAD_BYTES:
        raise ParseError("요청 문서가 동기 API의 100MB 한도를 초과합니다.")
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    try:
        async with asyncio.timeout(settings.timeout):
            response = await client.post(
                API_URL, data=request_options(settings),
                files={"document": (filename, content, media_type)},
            )
        if not response.is_success:
            raise ParseError(f"Upstage 요청이 실패했습니다(HTTP {response.status_code}). "
                             "인증·요청 한도·서비스 상태를 확인하세요.")
        payload = response.json()
    except (TimeoutError, httpx.TimeoutException) as error:
        raise ParseError("요청 제한 시간을 초과했습니다. 자동으로 재전송하지 않았습니다.") from error
    except httpx.RequestError as error:
        raise ParseError("Upstage에 연결할 수 없습니다. 자동으로 재전송하지 않았습니다.") from error
    except ValueError as error:
        if isinstance(error, ParseError):
            raise
        raise ParseError("API 응답을 JSON으로 읽을 수 없습니다.") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise ParseError("API 응답에 올바른 elements 목록이 없습니다.")
    return payload


def response_page_count(payload):
    """서비스가 제공한 페이지 수를 확인하고 없으면 미확인 상태로 둔다."""
    usage = payload.get("usage")
    if usage is None:
        return None
    if not isinstance(usage, dict):
        raise ParseError("API 응답의 usage 형식이 올바르지 않습니다.")
    count = usage.get("pages")
    if count is None:
        return None
    if type(count) is not int or not 1 <= count <= 100:
        raise ParseError("API 응답의 페이지 수가 허용 범위를 벗어났습니다.")
    return count


def group_pages(payload, offset=0, single_pdf_page=False):
    """요소 순서·Markdown 내용을 보존하며 API 페이지 번호로 묶는다."""
    groups = {}
    count = response_page_count(payload)
    if single_pdf_page and count not in (None, 1):
        raise ParseError("한 페이지 PDF 요청의 응답 페이지 수가 일치하지 않습니다.")
    for element in payload["elements"]:
        if not isinstance(element, dict):
            raise ParseError("API 요소 형식이 올바르지 않습니다.")
        page = element.get("page")
        if type(page) is not int or not 1 <= page <= (1 if single_pdf_page else 100):
            raise ParseError("API 요소의 페이지 번호가 올바르지 않습니다.")
        if count is not None and page > count:
            raise ParseError("API 요소의 페이지 번호가 보고된 페이지 수를 초과합니다.")
        contents = element.get("content")
        if not isinstance(contents, dict) or not isinstance(contents.get("markdown"), str):
            raise ParseError("API 요소에 Markdown 문자열이 없습니다.")
        coordinates = element.get("coordinates")
        if coordinates is not None and not isinstance(coordinates, list):
            raise ParseError("API 요소의 좌표 형식이 올바르지 않습니다.")
        groups.setdefault(page, []).append(element)
    return [Page(number=page + offset,
                 content=" ".join(element["content"]["markdown"] for element in groups[page]),
                 element_count=len(groups[page]),
                 coordinates=[element["coordinates"] for element in groups[page]
                              if element.get("coordinates") is not None])
            for page in sorted(groups)]


async def parse_document(source, settings, api_key, transport=None, progress=None):
    """문서 요청을 순차 실행하고 빈 결과·페이지 누락 가능성을 구분한다."""
    pages, models, issues = [], [], []
    request_count = 0
    total_pages = len(source.pdf.pages) if source.pdf is not None else None
    timeout = httpx.Timeout(settings.timeout, connect=min(settings.timeout, 15),
                            pool=min(settings.timeout, 15))
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout,
        follow_redirects=False, transport=transport,
    ) as client:
        for filename, content, offset in request_parts(source):
            if progress is not None:
                progress(request_count + 1, total_pages if source.pdf is not None else 1)
            payload = await send_request(client, settings, filename, content)
            request_count += 1
            pages.extend(group_pages(payload, offset, source.pdf is not None))
            if source.pdf is None:
                total_pages = response_page_count(payload)
            model = payload.get("model")
            if isinstance(model, str) and model and model not in models:
                models.append(model)
    if not pages or not any(page.content.strip() for page in pages):
        raise ParseError("파싱 결과에 내용이 없습니다. 성공 결과로 저장하지 않았습니다.")
    numbers = [page.number for page in pages]
    if len(numbers) != len(set(numbers)):
        raise ParseError("동일한 원본 페이지가 중복 반환되었습니다.")
    missing = sorted(set(range(1, (total_pages or max(numbers)) + 1)) - set(numbers))
    if missing:
        issues.append({"code": "pages_without_elements", "pages": missing,
                       "detail": "빈 페이지 또는 추출 누락 가능성 확인 필요"})
    empty = [page.number for page in pages if not page.content.strip()]
    if empty:
        issues.append({"code": "empty_page_content", "pages": empty})
    if total_pages is None:
        issues.append({"code": "total_pages_unknown", "detail": "문서 끝부분 누락 여부 확인 불가"})
    if not models:
        issues.append({"code": "response_model_unknown"})
    if source.pdf_warning_count:
        issues.append({"code": "pdf_library_warnings", "count": source.pdf_warning_count})
    return ParseResult(sorted(pages, key=lambda page: page.number), total_pages, request_count,
                       models, missing, issues)
