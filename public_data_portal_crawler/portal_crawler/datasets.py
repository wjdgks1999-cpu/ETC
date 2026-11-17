"""파일데이터·오픈API 목록을 화면 구조에 맞게 읽고 대상별 결과로 정리한다."""

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from .browser import navigate, no_results
from .common import CrawlConfig, CrawlResult, clean, set_query


def cards(driver, target: str):
    """대상에 맞는 목록 카드를 찾고, 찾지 못하면 다른 포털 목록 구조에서도 탐색한다."""
    suffix = "/fileData.do" if target == "file" else "/openapi.do"
    modern = driver.find_elements(By.CSS_SELECTOR, ".apply-result > .apply-result-item")
    matched = [card for card in modern if card.find_elements(By.CSS_SELECTOR, f'.apply-result-link a[href*="{suffix}"]')]
    if matched:
        return matched
    old_id = "fileDataList" if target == "file" else "apiDataList"
    return driver.find_elements(By.CSS_SELECTOR, f"#{old_id} > div.result-list > ul > li")


def metadata(card, label: str) -> str:
    """카드에서 제공기관·조회수 등 지정한 항목의 표시 값을 추출한다."""
    modern = card.find_elements(By.XPATH, f".//li[strong[normalize-space()='{label}']]")
    if modern:
        text = modern[0].text
        return clean(text[len(label):]) if text.startswith(label) else clean(text)
    old = card.find_elements(By.XPATH, f".//span[@class='tit' and normalize-space()='{label}']/following-sibling::span[@class='data'][1]")
    return clean(old[0].text) if old else ""


def parse_card(card, config: CrawlConfig) -> tuple[str, dict]:
    """카드 하나를 중복 확인용 식별자와 결과 행으로 변환한다. 필수 값이 없으면 예외를 낸다."""
    links = card.find_elements(By.CSS_SELECTOR, ".apply-result-link > a, dl > dt > a")
    if not links:
        raise ValueError("데이터명 링크를 찾지 못했습니다.")
    title = clean(links[0].text)
    provider = metadata(card, "제공기관")
    if not title or not provider:
        raise ValueError("데이터명 또는 제공기관이 비어 있습니다.")
    if config.target == "file":
        row = {"데이터명": title, "제공기관명": provider}
    else:
        views, applications = metadata(card, "조회수"), metadata(card, "활용신청")
        if not views or not applications:
            raise ValueError(f"조회수/활용신청 값을 찾지 못했습니다: {title}")
        row = {"기관명": provider, "유형": "오픈API", "데이터명": title,
               "조회수": views, "활용신청건수": applications}
    return links[0].get_attribute("href") or f"{provider}|{title}", row


def collect(driver, config: CrawlConfig, result: CrawlResult, checkpoint):
    """설정한 범위의 목록을 수집하며 중복을 제외하고, 항목 오류를 기록한 뒤 페이지별로 저장한다."""
    seen = set()
    previous_signature = None
    attempted = 0
    for page in config.pages():
        result.current_page = page
        navigate(driver, set_query(config.url, currentPage=page), config.delay)
        def loaded(d):
            """목록 카드나 명시적인 빈 결과가 확인되면 반환하고, 로딩 중이면 대기를 계속한다."""
            found = cards(d, config.target)
            return (found,) if found else (([],) if no_results(d) else False)
        items = WebDriverWait(driver, config.wait).until(loaded)[0]
        result.pages += 1
        if not items:
            result.stopped = "no-results"
            break
        signature = tuple((card.find_elements(By.CSS_SELECTOR, ".apply-result-link > a, dl > dt > a")[0].get_attribute("href")
                           if card.find_elements(By.CSS_SELECTOR, ".apply-result-link > a, dl > dt > a") else card.text)
                          for card in items)
        if signature == previous_signature:
            result.stopped = "repeated-page"
            break
        previous_signature = signature
        attempted_before = attempted
        for order, card in enumerate(items, 1):
            try:
                key, row = parse_card(card, config)
                if key in seen:
                    continue
                seen.add(key)
                result.rows.append(row)
            except Exception as error:
                result.add_error(page, str(order), error)
            attempted += 1
            if config.max_items is not None and attempted >= config.max_items:
                result.stopped = "item-limit"
                checkpoint()
                return
        checkpoint()
        print(f"[{page}페이지] 성공 {result.succeeded} / 실패 {result.failed}", flush=True)
        if attempted == attempted_before:
            result.stopped = "no-new-items"
            break
    else:
        result.stopped = "page-limit"
