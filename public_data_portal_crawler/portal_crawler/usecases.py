"""활용사례 목록과 상세 정보를 추출하며, 화면 구조에 따른 대체 탐색을 지원한다."""
import json
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .browser import navigate, no_results
from .common import CrawlConfig, CrawlResult, clean, set_query

DEVELOPMENT_TYPES = ("웹사이트", "모바일앱", "데스크톱앱", "모바일웹", "응용프로그램", "기타")
DATA_TYPES = ("오픈API", "파일데이터", "표준데이터셋", "표준데이터")
SCRIPT_DIR = Path(__file__).parent / "scripts"
CARD_SNAPSHOT_JS = (SCRIPT_DIR / "usecase_cards.js").read_text(encoding="utf-8")
CLICK_CARD_JS = (SCRIPT_DIR / "usecase_click.js").read_text(encoding="utf-8")

def make_detail_url(list_url: str, sn: str) -> str:
    """목록 URL의 검색 조건을 유지하며 활용사례 일련번호를 담은 상세 URL을 만든다."""
    parts = urlsplit(list_url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params["prcuseCaseSn"] = sn
    path = parts.path.replace(
        "selectPublicUseCaseListView.do", "selectPublicUseCaseView.do"
    )
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(params), ""))


def snapshot_items(driver: webdriver.Chrome) -> tuple[list[dict], dict]:
    """목록의 카드 정보를 읽어 공통 항목 형식으로 정리하고 탐색 진단 정보와 함께 반환한다."""
    result = driver.execute_script(CARD_SNAPSHOT_JS, list(DEVELOPMENT_TYPES)) or {}
    raw_items = result.get("items", []) if isinstance(result, dict) else []
    diagnostics = result.get("diagnostics", {}) if isinstance(result, dict) else {}

    items: list[dict] = []
    for raw in raw_items:
        sn = clean(str(raw.get("sn", "")))
        detail_url = clean(str(raw.get("detailUrl", "")))
        if not detail_url and sn:
            detail_url = make_detail_url(driver.current_url, sn)

        items.append(
            {
                "key": clean(str(raw.get("key", ""))),
                "sn": sn,
                "title": clean(str(raw.get("title", ""))),
                "date": clean(str(raw.get("date", ""))),
                "card_text": clean(str(raw.get("cardText", ""))),
                "detail_url": detail_url,
            }
        )
    return items, diagnostics


def wait_list(driver: webdriver.Chrome, wait: WebDriverWait) -> tuple[list[dict], dict]:
    """활용사례 목록 또는 명시적인 빈 결과를 기다린다. 시간 초과 시 마지막 진단을 예외에 포함한다."""
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    wait.until(
        lambda d: "공공데이터 활용사례" in d.find_element(By.TAG_NAME, "body").text
    )

    last_diagnostics: dict = {}

    def loaded(d: webdriver.Chrome):
        """카드 탐색 결과와 진단 정보를 갱신하고, 목록 로딩이 완료됐는지 판별한다."""
        nonlocal last_diagnostics
        items, diagnostics = snapshot_items(d)
        last_diagnostics = diagnostics
        if not items and no_results(d):
            return ([], diagnostics)
        return (items, diagnostics) if items else False

    try:
        return wait.until(loaded)
    except TimeoutException as error:
        raise TimeoutException(
            f"카드 탐색 실패: {last_diagnostics}"
        ) from error


def wait_detail(driver: webdriver.Chrome, wait: WebDriverWait) -> None:
    """상세 화면의 서비스 설명·개발유형·활용 데이터 문구가 표시될 때까지 기다린다."""
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    wait.until(
        lambda d: (
            "서비스 설명" in d.find_element(By.TAG_NAME, "body").text
            and "개발유형" in d.find_element(By.TAG_NAME, "body").text
            and "활용 데이터" in d.find_element(By.TAG_NAME, "body").text
        )
    )


def click_item(driver: webdriver.Chrome, item: dict) -> dict:
    """제목과 날짜로 목록 카드를 찾아 클릭하고, 클릭 여부와 진단 정보를 반환한다."""
    return (
        driver.execute_script(
            CLICK_CARD_JS,
            {"title": item["title"], "date": item["date"]},
            list(DEVELOPMENT_TYPES),
        )
        or {}
    )


def get_lines(driver: webdriver.Chrome) -> list[str]:
    """화면 본문을 줄 단위로 나누어 공백을 정리하고 빈 줄을 제외한다."""
    body_text = driver.find_element(By.TAG_NAME, "body").text
    return [clean(line) for line in body_text.splitlines() if clean(line)]


def label_value(lines: list[str], label: str) -> str:
    """레이블과 같은 줄 또는 다음 줄에서 값을 찾고, 구분용 콜론과 공백을 제거한다."""
    for index, line in enumerate(lines):
        if line == label:
            return clean(lines[index + 1].lstrip(":")) if index + 1 < len(lines) else ""
        if line.startswith(label):
            value = clean(line[len(label) :].lstrip(" :"))
            if value:
                return value
    return ""


def between(lines: list[str], start: str, end: str) -> list[str]:
    """두 제목 사이의 본문 줄을 추출한다. 종료 제목은 띄어쓰기 차이를 허용한다."""
    try:
        start_index = next(
            i for i, line in enumerate(lines) if line.startswith(start)
        ) + 1
    except StopIteration:
        return []

    result: list[str] = []
    for line in lines[start_index:]:
        if line.replace(" ", "").startswith(end.replace(" ", "")):
            break
        result.append(line)
    return result


def service_name(lines: list[str]) -> str:
    """목록 제목을 사용할 수 없을 때 개발유형 앞줄을 서비스명 후보로 반환한다."""
    for index, line in enumerate(lines):
        if line.startswith("개발유형") and index > 0:
            return lines[index - 1]
    return ""


def service_url(driver: webdriver.Chrome, lines: list[str]) -> str:
    """서비스 URL 구역의 링크나 본문 주소를 추출하고, 활용 데이터 링크와 구분한다."""
    links = driver.find_elements(By.XPATH,
        "//li[contains(., '서비스 URL')]//a | "
        "//tr[th[contains(., '서비스 URL')]]/td//a | "
        "//dt[contains(., '서비스 URL')]/following-sibling::dd[1]//a")
    for link in links:
        href = clean(link.get_attribute("href"))
        if href and not href.lower().startswith("javascript"):
            return href
    value = label_value(lines, "서비스 URL")
    return value if value.startswith(("https://", "http://")) else ""


def used_data(lines: list[str]) -> list[dict[str, str]]:
    """한 줄 또는 여러 줄로 표시된 활용 데이터의 유형·이름을 읽고 중복을 제거한다."""
    section = between(lines, "활용 데이터", "기타정보")
    result: list[dict[str, str]] = []

    for line in section:
        for data_type in DATA_TYPES:
            if line == data_type:
                # 실제 이름은 다음 행에서 처리하기 위해 여기서는 건너뛴다.
                break
            if line.startswith(data_type + " "):
                name = clean(line[len(data_type) :])
                if name:
                    item = {"데이터유형": data_type, "데이터명": name}
                    if item not in result:
                        result.append(item)
                break

    # 유형과 데이터명이 서로 다른 줄로 표시되는 화면도 지원한다.
    index = 0
    while index < len(section):
        if section[index] in DATA_TYPES and index + 1 < len(section):
            data_type = section[index]
            name = section[index + 1]
            if name and not any(name.startswith(t) for t in DATA_TYPES):
                item = {"데이터유형": data_type, "데이터명": name}
                if item not in result:
                    result.append(item)
            index += 2
        else:
            index += 1

    return result


def extract_sn(url: str) -> str:
    """상세 URL의 쿼리에서 활용사례 일련번호를 추출한다."""
    params = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
    return clean(params.get("prcuseCaseSn", ""))


def scrape_detail(
    driver: webdriver.Chrome,
    page_no: int,
    order: int,
    item: dict,
) -> dict:
    """상세 정보를 목록 정보로 보완해 서비스 정보와 연결 데이터가 담긴 결과 행을 만든다."""
    lines = get_lines(driver)
    data_list = used_data(lines)

    return {
        "페이지": page_no,
        "페이지내순번": order,
        "활용사례일련번호": extract_sn(driver.current_url) or item.get("sn", ""),
        "서비스명": item.get("title") or service_name(lines),
        "개발유형": label_value(lines, "개발유형"),
        "서비스설명": "\n".join(
            between(lines, "서비스 설명", "기능 및 서비스화면")
        ),
        "서비스URL": service_url(driver, lines),
        "등록일": label_value(lines, "등록일") or item.get("date", ""),
        "활용데이터수": len(data_list),
        "활용데이터목록": json.dumps(data_list, ensure_ascii=False),
        "상세페이지URL": driver.current_url,
        "수집오류": "",
        "_data": data_list,
    }


def collect(driver, config: CrawlConfig, result: CrawlResult, checkpoint):
    """설정한 범위의 활용사례를 수집한다. 상세 실패도 결과에 남기고 항목마다 중간 저장한다."""
    wait = WebDriverWait(driver, config.wait)
    seen = set()
    previous_signature = None
    for page in config.pages():
        result.current_page = page
        page_url = set_query(config.url, pageIndex=page)
        navigate(driver, page_url, config.delay)
        items, _ = wait_list(driver, wait)
        result.pages += 1
        if not items:
            result.stopped = "no-results"
            break
        signature = tuple(item["key"] for item in items)
        if signature == previous_signature:
            result.stopped = "repeated-page"
            break
        previous_signature = signature
        seen_before = len(seen)
        for order, item in enumerate(items, 1):
            key = item.get("sn") or item["key"]
            if key in seen:
                continue
            seen.add(key)
            try:
                time.sleep(config.delay)
                clicked = click_item(driver, item)
                if not clicked.get("clicked"):
                    raise RuntimeError(f"카드 클릭 대상 탐색 실패: {clicked.get('reason', '')}")
                try:
                    wait_detail(driver, WebDriverWait(driver, config.detail_wait))
                except TimeoutException:
                    if not item.get("detail_url"):
                        raise RuntimeError("상세 화면으로 이동하지 않았고 상세 URL도 없습니다.")
                    navigate(driver, item["detail_url"], config.delay)
                    wait_detail(driver, wait)
                result.rows.append(scrape_detail(driver, page, order, item))
            except Exception as error:
                result.add_error(page, item["title"], error)
                result.rows.append({"페이지": page, "페이지내순번": order,
                                    "활용사례일련번호": item.get("sn", ""),
                                    "서비스명": item["title"], "등록일": item.get("date", ""),
                                    "활용데이터수": 0, "활용데이터목록": "[]",
                                    "상세페이지URL": item.get("detail_url", ""),
                                    "수집오류": str(error), "_data": []})
            checkpoint()
            print(f"[{page}:{order}] 성공 {result.succeeded} / 실패 {result.failed}", flush=True)
            if config.max_items is not None and len(seen) >= config.max_items:
                result.stopped = "item-limit"
                return
            if order < len(items):
                navigate(driver, page_url, config.delay)
                wait_list(driver, wait)
        if len(seen) == seen_before:
            result.stopped = "no-new-items"
            break
    else:
        result.stopped = "page-limit"
