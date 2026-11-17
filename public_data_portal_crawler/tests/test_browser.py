"""로컬 가상 HTML을 실제 Chrome에서 읽는 선택적 검증이다. 포털에는 접속하지 않는다."""

import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from portal_crawler import datasets, usecases
from portal_crawler.browser import browser_session, no_results
from portal_crawler.common import CrawlConfig
from portal_crawler.defaults import DEFAULT_URLS


@unittest.skipUnless(os.environ.get("CRAWLER_BROWSER_TESTS") == "1", "set CRAWLER_BROWSER_TESTS=1 to run local Chrome fixtures")
class BrowserFixtureTests(unittest.TestCase):
    """화면 구조별 추출·클릭 동작을 가상 HTML로 검증한다."""

    @classmethod
    def setUpClass(cls):
        """이 검증 묶음에서 공유할 창 없는 Chrome을 생성한다."""
        cls.config = CrawlConfig("api", DEFAULT_URLS["api"], Path("unused.xlsx"), headless=True)
        cls.session = browser_session(cls.config)
        cls.driver = cls.session.__enter__()

    @classmethod
    def tearDownClass(cls):
        """검증 묶음이 끝나면 공유 브라우저를 종료한다."""
        cls.session.__exit__(None, None, None)

    def setUp(self):
        """각 검증 전에 가상 HTML을 다시 열어 화면 상태를 초기화한다."""
        self.driver.get((Path(__file__).parent / "fixtures" / "portal.html").as_uri())

    def test_modern_targets_are_separate_and_real_provider_is_used(self):
        """파일·API 카드가 구분되고 각 카드의 제공기관과 집계 값이 추출되는지 확인한다."""
        api = datasets.cards(self.driver, "api")
        files = datasets.cards(self.driver, "file")
        self.assertEqual((len(api), len(files)), (1, 1))
        _, row = datasets.parse_card(api[0], self.config)
        self.assertEqual(row, {"기관명": "다른기관", "유형": "오픈API", "데이터명": "예제 API", "조회수": "1,234회", "활용신청건수": "56건"})
        cfg = CrawlConfig("file", DEFAULT_URLS["file"], Path("unused.xlsx"))
        self.assertEqual(datasets.parse_card(files[0], cfg)[1]["제공기관명"], "예제기관")

    def test_alternate_portal_layout_and_api_column_name(self):
        """대체 목록 구조에서도 API 정보를 같은 출력 열로 추출하는지 확인한다."""
        self.driver.execute_script("document.querySelector('.apply-result').remove()")
        cfg = CrawlConfig("api", DEFAULT_URLS["api"], Path("unused.xlsx"))
        items = datasets.cards(self.driver, "api")
        self.assertEqual(len(items), 1)
        row = datasets.parse_card(items[0], cfg)[1]
        self.assertEqual(row["활용신청건수"], "3")
        self.assertEqual(row["기관명"], "예제기관")

    def test_usecase_snapshot_and_click(self):
        """활용사례의 제목·일련번호를 추출하고 해당 카드를 클릭하는지 확인한다."""
        items, _ = usecases.snapshot_items(self.driver)
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]["title"], items[0]["sn"]), ("가상 서비스", "123456"))
        self.assertTrue(usecases.click_item(self.driver, items[0])["clicked"])
        self.assertEqual(self.driver.execute_script("return window.selectedCase"), "123456")

    def test_missing_service_url_and_explicit_empty_result(self):
        """서비스 URL이 없을 때 데이터 링크를 사용하지 않으며, 빈 결과 안내를 구분하는지 확인한다."""
        self.assertEqual(usecases.service_url(self.driver, usecases.get_lines(self.driver)), "")
        self.assertFalse(no_results(self.driver))
        self.driver.execute_script("document.querySelector('#contents').textContent=arguments[0]", "검색 결과가 없습니다.")
        self.assertTrue(no_results(self.driver))


if __name__ == "__main__":
    unittest.main()
