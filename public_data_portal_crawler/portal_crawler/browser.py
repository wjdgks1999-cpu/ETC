"""브라우저 생성·종료, 페이지 이동과 진단 자료 저장을 담당한다."""

from contextlib import contextmanager
from pathlib import Path
import time
import warnings

from selenium import webdriver

from .common import CrawlConfig


def make_driver(config: CrawlConfig):
    """설정에 맞는 Chrome을 생성하고 페이지 로딩 제한 시간을 적용한다."""
    options = webdriver.ChromeOptions()
    if config.headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1600,1200")
    options.add_argument("--lang=ko-KR")
    options.add_argument("--disable-notifications")
    driver = webdriver.Chrome(options=options)
    try:
        driver.set_page_load_timeout(config.wait + 30)
    except BaseException:
        driver.quit()
        raise
    return driver


@contextmanager
def browser_session(config: CrawlConfig):
    """수집에 사용할 브라우저를 제공하고, 작업 종료 시 예외 여부와 관계없이 종료를 시도한다."""
    driver = make_driver(config)
    try:
        yield driver
    finally:
        # 저장 실패가 브라우저 정리를 건너뛰게 하거나 종료 오류가 원래 예외를 가리지 않게 한다.
        try:
            driver.quit()
        except Exception as error:
            warnings.warn(f"브라우저 종료 실패: {error}", RuntimeWarning)


def navigate(driver, url: str, delay: float):
    """요청 간격만큼 대기한 뒤 지정한 URL로 이동한다."""
    time.sleep(delay)
    driver.get(url)


def no_results(driver) -> bool:
    """포털에 검색 결과가 없다는 안내가 명시된 경우에만 빈 목록으로 판단한다."""
    from selenium.webdriver.common.by import By
    containers = driver.find_elements(By.CSS_SELECTOR, "#contents")
    text = containers[0].text if containers else ""
    return any(message in text for message in (
        "검색 결과가 없습니다", "검색결과가 없습니다", "검색된 결과가 없습니다",
        "검색된 데이터가 없습니다", "등록된 데이터가 없습니다",
    ))


def save_debug(driver, directory: Path, reason: str):
    """현재 페이지의 HTML·화면·오류 정보를 저장하며, 진단 저장 실패는 경고로 남긴다."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "page.html").write_text(driver.page_source, encoding="utf-8")
        driver.save_screenshot(str(directory / "page.png"))
        (directory / "error.txt").write_text(
            f"URL: {driver.current_url}\n{reason}\n", encoding="utf-8")
    except Exception as error:
        warnings.warn(f"진단 파일 저장 실패: {error}", RuntimeWarning)
