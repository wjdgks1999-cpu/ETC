"""공공데이터포털 수집 실행 진입점. 옵션은 `python crawl.py --help`로 확인한다."""

from portal_crawler.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
