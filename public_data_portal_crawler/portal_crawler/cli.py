"""수집 대상과 실행 옵션을 해석하고 수집 결과를 안내한다."""

import argparse
from pathlib import Path
import sys

from .common import CrawlConfig
from .defaults import DEFAULT_URLS


def parse_args(argv=None) -> CrawlConfig:
    """실행 인수를 수집 설정으로 변환한다. 잘못된 값은 사용법 안내와 함께 거부한다."""
    parser = argparse.ArgumentParser(description="공공데이터포털 정보를 Excel로 수집합니다.")
    parser.add_argument("--target", choices=["file", "api", "usecase"], required=True)
    parser.add_argument("--url", help="검색 조건을 설정한 포털 목록 URL (기본값: 국토교통부 관련 검색)")
    parser.add_argument("--output", type=Path, help="출력 .xlsx 경로")
    parser.add_argument("--start-page", type=int, default=1)
    limit = parser.add_mutually_exclusive_group()
    limit.add_argument("--max-pages", type=int, default=1, help="수집할 페이지 수 (기본: 1)")
    limit.add_argument("--all-pages", action="store_true", help="빈 목록 또는 반복 페이지까지 수집")
    parser.add_argument("--max-items", type=int, help="최대 처리 항목 수 (실패 포함)")
    parser.add_argument("--wait", type=float, default=30, help="목록 대기시간, 초")
    parser.add_argument("--detail-wait", type=float, default=10, help="상세 화면 대기시간, 초")
    parser.add_argument("--delay", type=float, default=0.7, help="페이지 요청 간격, 초")
    parser.add_argument("--headless", action="store_true", help="브라우저 창을 표시하지 않음")
    parser.add_argument("--overwrite", action="store_true", help="기존 출력 파일 교체 허용")
    args = parser.parse_args(argv)
    output = args.output or Path("outputs") / f"{args.target}.xlsx"
    try:
        return CrawlConfig(target=args.target, url=args.url or DEFAULT_URLS[args.target],
                           output=output, start_page=args.start_page,
                           max_pages=None if args.all_pages else args.max_pages, max_items=args.max_items,
                           wait=args.wait, detail_wait=args.detail_wait, delay=args.delay,
                           headless=args.headless, overwrite=args.overwrite)
    except ValueError as error:
        parser.error(str(error))


def main(argv=None) -> int:
    """수집을 실행하고 요약을 출력한다. 정상 종료는 0, 실행 실패는 1을 반환한다."""
    config = parse_args(argv)
    try:
        from .runner import run
        result = run(config)
    except Exception as error:
        print(f"실행 실패: {error}", file=sys.stderr)
        return 1
    print(f"수집 종료: 성공 {result.succeeded} / 실패 {result.failed} / 확인한 페이지 {result.pages}")
    print(f"종료 사유: {result.stopped}")
    print(f"출력 기준 경로: {config.output.resolve()}")
    print(f"진행 상태: {config.output.with_suffix('.status.json').resolve()}")
    return result.exit_code
