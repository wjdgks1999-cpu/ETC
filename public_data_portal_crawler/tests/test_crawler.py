"""외부 접속 없이 실행 설정, 추출, 파일 보존과 오류 처리를 검증한다."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from portal_crawler import browser, datasets, export, runner, usecases
from portal_crawler.cli import parse_args
from portal_crawler.common import CrawlConfig, CrawlResult, set_query
from portal_crawler.defaults import DEFAULT_URLS


def config(target="file", **kwargs):
    """검증에 필요한 값만 덮어써 기본 수집 설정을 만든다."""
    return CrawlConfig(target, DEFAULT_URLS[target], kwargs.pop("output", Path("unused.xlsx")), **kwargs)


class ConfigurationTests(unittest.TestCase):
    """실행 옵션, URL 변환과 진입점 가져오기의 동작을 검증한다."""
    def test_url_keeps_repeated_and_blank_filters(self):
        """페이지 인수 변경 시 중복 쿼리·빈 값·URL 조각이 유지되는지 확인한다."""
        url = set_query("https://www.data.go.kr/list?a=1&a=2&blank=&currentPage=1#results", currentPage=3)
        self.assertEqual(parse_qs(urlsplit(url).query, keep_blank_values=True),
                         {"a": ["1", "2"], "blank": [""], "currentPage": ["3"]})
        self.assertEqual(urlsplit(url).fragment, "results")

    def test_target_defaults_and_explicit_page_limit(self):
        """대상별 기본 출력과 페이지 수, 명시한 수집 범위가 적용되는지 확인한다."""
        for target in ("file", "api", "usecase"):
            settings = parse_args(["--target", target])
            self.assertEqual(settings.max_pages, 1)
            self.assertEqual(settings.output, Path("outputs") / f"{target}.xlsx")
            self.assertEqual(parse_args(["--target", target, "--max-pages", "3"]).max_pages, 3)
            self.assertIsNone(parse_args(["--target", target, "--all-pages"]).max_pages)

    def test_invalid_options_rejected_before_browser(self):
        """잘못된 범위·대기시간·URL·출력 형식이 실행 전에 거부되는지 확인한다."""
        for args in (("--max-pages", "0"), ("--start-page", "-1"), ("--delay", "nan"),
                     ("--wait", "0"), ("--output", "a.csv"),
                     ("--url", DEFAULT_URLS["api"]), ("--url", "https://example.com/")):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parse_args(["--target", "file", *args])

    def test_page_range_is_count_from_start(self):
        """페이지 수가 시작 페이지를 기준으로 계산되는지 확인한다."""
        self.assertEqual(list(config(start_page=3, max_pages=2).pages()), [3, 4])

    def test_importing_entry_point_does_not_launch_browser(self):
        """실행 모듈을 가져오기만 할 때 브라우저가 시작되지 않는지 확인한다."""
        with patch.object(browser.webdriver, "Chrome") as chrome:
            spec = importlib.util.spec_from_file_location("crawl", ROOT / "crawl.py")
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
            chrome.assert_not_called()


class ExtractionTests(unittest.TestCase):
    """상세 화면의 값 정리와 잘못된 항목 연결 방지를 검증한다."""
    def test_detail_colons_and_data_end_marker(self):
        """항목 값의 콜론이 제거되고 활용 데이터 구간의 끝이 구분되는지 확인한다."""
        lines = ["개발유형 : 웹사이트", "등록일 : 2026-11-12", "활용 데이터",
                 "오픈API", "예제 데이터", "예제 데이터", "설명", "기타 정보", "파일데이터 제외"]
        self.assertEqual(usecases.label_value(lines, "개발유형"), "웹사이트")
        self.assertEqual(usecases.label_value(lines, "등록일"), "2026-11-12")
        self.assertEqual(usecases.used_data(lines), [{"데이터유형": "오픈API", "데이터명": "예제 데이터"}])

    def test_inline_and_separate_data_rows_are_deduplicated(self):
        """줄 배치가 다른 동일 활용 데이터가 중복 결과로 남지 않는지 확인한다."""
        self.assertEqual(usecases.used_data(["활용 데이터", "파일데이터 예제", "파일데이터", "예제", "기타정보"]),
                         [{"데이터유형": "파일데이터", "데이터명": "예제"}])

    def test_list_title_wins_over_category_before_development_type(self):
        """분류명이 서비스명으로 잘못 쓰이지 않고 목록 제목이 우선되는지 확인한다."""
        driver = Mock(current_url="https://www.data.go.kr/tcs/puc/selectPublicUseCaseView.do?prcuseCaseSn=123456")
        with patch.object(usecases, "get_lines", return_value=["실제 서비스", "교통물류", "개발유형 : 웹사이트"]), patch.object(usecases, "service_url", return_value=""):
            row = usecases.scrape_detail(driver, 1, 1, {"title": "실제 서비스"})
        self.assertEqual(row["서비스명"], "실제 서비스")
        self.assertEqual(row["개발유형"], "웹사이트")

    def test_missing_service_url_is_not_data_source_url(self):
        """서비스 주소가 없으면 데이터 출처 주소로 대체하지 않는지 확인한다."""
        driver = Mock()
        driver.find_elements.return_value = []
        self.assertEqual(usecases.service_url(driver, ["서비스 URL :", "등록일 : 2026-11-12"]), "")


class ExportTests(unittest.TestCase):
    """출력 열·파일 형식과 저장 실패 시 원본 보존을 검증한다."""
    def setUp(self):
        """각 저장 검증에 사용할 임시 폴더를 만들고 종료 시 정리하도록 등록한다."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / "result.xlsx"

    def test_api_columns_and_literal_excel_text(self):
        """API 출력 열과 수식처럼 보이는 수집 문자열의 문자 저장을 확인한다."""
        row = {"기관명": "예제기관", "유형": "오픈API", "데이터명": "=1+1", "조회수": "2회", "활용신청건수": "1건"}
        export.save(config("api", output=self.output), CrawlResult(rows=[row]))
        book = load_workbook(self.output)
        self.assertEqual([cell.value for cell in book.active[1]], list(row))
        self.assertEqual(book.active["C2"].value, "=1+1")
        self.assertEqual(book.active["C2"].data_type, "s")
        book.close()

    def test_usecase_sheets_csv_and_status(self):
        """활용사례의 두 시트, CSV 인코딩과 상태 집계가 저장되는지 확인한다."""
        row = {"서비스명": "예제 서비스", "활용사례일련번호": "123456", "수집오류": "",
               "_data": [{"데이터유형": "오픈API", "데이터명": "예제"}]}
        export.save(config("usecase", output=self.output), CrawlResult(rows=[row]))
        book = load_workbook(self.output, read_only=True)
        self.assertEqual(book.sheetnames, ["활용사례", "활용데이터"])
        self.assertEqual(book["활용데이터"].max_row, 2)
        book.close()
        self.assertTrue(self.output.with_suffix(".csv").read_bytes().startswith(b"\xef\xbb\xbf"))
        status = json.loads(self.output.with_suffix(".status.json").read_text(encoding="utf-8"))
        self.assertEqual((status["succeeded"], status["failed"]), (1, 0))

    def test_existing_output_requires_explicit_overwrite(self):
        """기존 출력의 교체가 명시적으로 허용된 경우에만 진행되는지 확인한다."""
        self.output.write_bytes(b"original")
        with self.assertRaises(FileExistsError):
            export.check_output(config(output=self.output))
        export.check_output(config(output=self.output, overwrite=True))

    def test_failed_first_page_preserves_existing_workbook(self):
        """첫 목록 수집에 실패했을 때 기존 Excel을 빈 결과로 바꾸지 않는지 확인한다."""
        self.output.write_bytes(b"original")
        result = CrawlResult(stopped="error")
        result.add_error(1, "list", RuntimeError("timeout"))
        export.save(config(output=self.output, overwrite=True), result)
        self.assertEqual(self.output.read_bytes(), b"original")
        self.assertEqual(result.exit_code, 1)

    def test_failed_temporary_write_preserves_existing_file(self):
        """임시 파일 작성 실패 시 원본을 보존하고 임시 파일을 정리하는지 확인한다."""
        self.output.write_bytes(b"original")
        def fail(path):
            """일부 내용을 쓴 직후 저장 오류를 발생시켜 불완전한 쓰기를 재현한다."""
            path.write_bytes(b"partial")
            raise OSError("disk full")
        with self.assertRaises(OSError):
            export.atomic_write(self.output, fail)
        self.assertEqual(self.output.read_bytes(), b"original")
        self.assertEqual(list(self.output.parent.glob(".crawl-*")), [])


class LifecycleTests(unittest.TestCase):
    """수집 종료 조건, 부분 실패 기록과 브라우저 정리를 검증한다."""
    def test_dataset_page_limit_and_checkpoint_state(self):
        """중간 저장은 진행 중으로 표시하고 페이지 제한 도달 후 종료 상태를 갱신하는지 확인한다."""
        card = Mock()
        card.find_elements.return_value = [Mock(**{"get_attribute.return_value": "item1"})]
        state = CrawlResult()
        checkpoints = []
        with patch.object(datasets, "navigate"), patch.object(datasets, "cards", return_value=[card]), patch.object(datasets, "parse_card", return_value=("item1", {"데이터명": "예제"})):
            datasets.collect(Mock(), config(), state, lambda: checkpoints.append(state.stopped))
        self.assertEqual(checkpoints, ["running"])
        self.assertEqual((state.succeeded, state.stopped), (1, "page-limit"))

    def test_repeated_page_stops_unbounded_collection(self):
        """전체 페이지 수집 중 같은 목록이 반복되면 종료하는지 확인한다."""
        card = Mock()
        card.find_elements.return_value = [Mock(**{"get_attribute.return_value": "item1"})]
        state = CrawlResult()
        with patch.object(datasets, "navigate"), patch.object(datasets, "cards", return_value=[card]), patch.object(datasets, "parse_card", return_value=("item1", {"데이터명": "예제"})):
            datasets.collect(Mock(), config(max_pages=None), state, lambda: None)
        self.assertEqual((state.succeeded, state.pages, state.stopped), (1, 2, "repeated-page"))

    def test_explicit_empty_page_is_not_a_parse_failure(self):
        """명시적인 빈 결과가 추출 오류로 집계되지 않는지 확인한다."""
        state = CrawlResult()
        with patch.object(datasets, "navigate"), patch.object(datasets, "cards", return_value=[]), patch.object(datasets, "no_results", return_value=True):
            datasets.collect(Mock(), config(), state, lambda: None)
        self.assertEqual((state.succeeded, state.failed, state.stopped), (0, 0, "no-results"))

    def test_partial_dataset_row_failures_are_reported(self):
        """개별 데이터 추출 실패가 오류 수와 실패 종료 코드에 반영되는지 확인한다."""
        card = Mock()
        card.find_elements.return_value = []
        state = CrawlResult()
        with patch.object(datasets, "navigate"), patch.object(datasets, "cards", return_value=[card]), patch.object(datasets, "parse_card", side_effect=ValueError("missing count")):
            datasets.collect(Mock(), config(), state, lambda: None)
        self.assertEqual((state.succeeded, state.failed, state.exit_code), (0, 1, 1))

    def test_browser_closes_when_final_export_fails(self):
        """최종 파일 저장에 실패해도 브라우저 종료가 호출되는지 확인한다."""
        driver = Mock()
        with patch.object(browser, "make_driver", return_value=driver), patch.object(runner, "check_output"), patch.object(datasets, "collect"), patch.object(runner, "save", side_effect=OSError("file locked")):
            with self.assertRaises(OSError):
                runner.run(config())
        driver.quit.assert_called_once()

    def test_failed_page_is_reported_and_partial_rows_survive(self):
        """후속 페이지 실패 시 먼저 수집한 행을 보존하고 실패 페이지를 기록하는지 확인한다."""
        def fail(driver, cfg, result, checkpoint):
            """결과 한 행을 추가한 뒤 다음 페이지 오류를 발생시켜 부분 수집 실패를 재현한다."""
            result.rows.append({"데이터명": "예제", "제공기관명": "기관"})
            result.current_page = 2
            raise RuntimeError("list unavailable")
        driver = Mock()
        with patch.object(browser, "make_driver", return_value=driver), patch.object(runner, "check_output"), patch.object(datasets, "collect", side_effect=fail), patch.object(runner, "save"), patch.object(runner, "save_debug"):
            result = runner.run(config())
        self.assertEqual((result.succeeded, result.failed, result.exit_code), (1, 1, 1))
        self.assertEqual(result.errors[0]["페이지"], 2)
        driver.quit.assert_called_once()

    def test_failed_details_are_not_counted_as_success(self):
        """상세 수집 실패 행이 성공 건수에 포함되지 않는지 확인한다."""
        result = CrawlResult(rows=[{"수집오류": "timeout"}, {"수집오류": ""}])
        result.add_error(1, "detail", RuntimeError("timeout"))
        self.assertEqual((result.succeeded, result.failed, result.exit_code), (1, 1, 1))


if __name__ == "__main__":
    unittest.main()
