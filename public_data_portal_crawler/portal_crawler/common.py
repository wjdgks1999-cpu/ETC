"""수집 설정, 결과 집계와 공통 문자열·URL 처리를 정의한다."""

from dataclasses import dataclass, field
from pathlib import Path
import math
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def clean(value: str | None) -> str:
    """줄 내부의 탭·연속 공백과 양끝 공백을 정리한 문자열을 반환한다."""
    return re.sub(r"[\t\r ]+", " ", value or "").strip()


def set_query(url: str, **updates: str | int) -> str:
    """지정한 쿼리 인수만 교체하고, 다른 인수의 중복 값·빈 값과 URL 조각은 유지한다."""
    parts = urlsplit(url)
    pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k not in updates]
    pairs.extend((k, str(v)) for k, v in updates.items())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


@dataclass(frozen=True)
class CrawlConfig:
    """수집 대상·범위·대기시간·출력 경로를 보관하는 실행 설정이다."""
    target: str
    url: str
    output: Path
    start_page: int = 1
    max_pages: int | None = 1
    max_items: int | None = None
    wait: float = 30
    detail_wait: float = 10
    delay: float = 0.7
    headless: bool = False
    overwrite: bool = False

    def __post_init__(self):
        """URL·수집 범위·대기시간·출력 형식을 검증하고 출력 경로를 Path로 변환한다."""
        if self.target not in {"file", "api", "usecase"}:
            raise ValueError("지원 대상: file, api, usecase")
        parts = urlsplit(self.url)
        expected = ("/tcs/puc/selectPublicUseCaseListView.do" if self.target == "usecase"
                    else "/tcs/dss/selectDataSetList.do")
        if parts.scheme not in {"http", "https"} or parts.hostname not in {"data.go.kr", "www.data.go.kr"} or parts.path != expected:
            raise ValueError("수집 대상에 맞는 공공데이터포털 목록 URL을 지정하세요.")
        dtype = dict(parse_qsl(parts.query)).get("dType")
        if self.target != "usecase" and dtype != self.target.upper():
            raise ValueError("URL의 dType과 --target이 일치해야 합니다 (FILE/API).")
        if self.start_page < 1 or any(v is not None and v < 1 for v in (self.max_pages, self.max_items)):
            raise ValueError("페이지·건수는 1 이상이어야 합니다.")
        if any(not math.isfinite(v) or v <= 0 for v in (self.wait, self.detail_wait)) or not math.isfinite(self.delay) or self.delay < 0:
            raise ValueError("대기시간은 양수, 요청 간격은 0 이상의 유한한 수여야 합니다.")
        object.__setattr__(self, "output", Path(self.output))
        if self.output.suffix.lower() != ".xlsx":
            raise ValueError("출력 경로는 .xlsx 확장자여야 합니다.")

    def pages(self):
        """시작 페이지부터 설정한 개수만큼 번호를 생성한다. 개수 제한이 없으면 계속 생성한다."""
        page = self.start_page
        while self.max_pages is None or page < self.start_page + self.max_pages:
            yield page
            page += 1


@dataclass
class CrawlResult:
    """수집 결과 행, 오류 내역과 진행 상태를 함께 보관한다."""
    rows: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    pages: int = 0
    current_page: int = 0
    stopped: str = "running"

    @property
    def succeeded(self) -> int:
        """수집 오류가 없는 결과 행의 수를 반환한다."""
        return sum(not row.get("수집오류") for row in self.rows)

    @property
    def failed(self) -> int:
        """항목 수집과 목록·저장 단계에서 기록된 오류 수를 반환한다."""
        return len(self.errors)

    @property
    def exit_code(self) -> int:
        """기록된 오류가 있으면 실패 코드 1, 없으면 정상 코드 0을 반환한다."""
        return 1 if self.errors else 0

    def add_error(self, page: int, item: str, error: Exception):
        """오류가 발생한 페이지·항목과 예외 메시지를 결과에 추가한다."""
        self.errors.append({"페이지": page, "항목": item, "오류": str(error)})
