"""메타데이터 비교와 제외 사유 검토를 하나의 명령으로 제공한다."""

import argparse
import asyncio
from pathlib import Path

from .config import BASE_DIR, ReviewConfig
from .schemas import InputError


def parse_args(argv=None):
    """공통 입력 경로와 비교·검토별 실행 옵션을 읽는다."""
    parser = argparse.ArgumentParser(description="메타데이터 비교와 공공데이터 개방 제외 사유 검토")
    commands = parser.add_subparsers(dest="command", required=True)
    compare = commands.add_parser("compare", help="검토 전 테이블명 일치·누락 비교")
    review = commands.add_parser("run", help="제외 코드·사유 작성 및 검수")
    for command in (compare, review):
        command.add_argument("--tables", type=Path, default=BASE_DIR / "테이블정보.xlsx")
        command.add_argument("--columns", type=Path, default=BASE_DIR / "컬럼정보.xlsx")
        command.add_argument("--table-sheet")
        command.add_argument("--column-sheet")
    compare.add_argument("--show-common", action="store_true")
    compare.add_argument("--output", type=Path, help="비교 결과 CSV 경로")
    review.add_argument("--limit", type=int)
    review.add_argument("--max-concurrency", type=int, default=5)
    destinations = review.add_mutually_exclusive_group()
    destinations.add_argument("--output", type=Path, help="검토 결과 .xlsx 경로")
    destinations.add_argument("--output-dir", type=Path, default=BASE_DIR / "outputs")
    review.add_argument("--overwrite", action="store_true")
    review.add_argument("--model", help="모델 이름. 생략하면 OPENAI_MODEL 사용")
    review.add_argument("--env-file", type=Path, default=BASE_DIR / ".env")
    review.add_argument("--prompt-dir", type=Path, default=BASE_DIR / "prompt")
    args = parser.parse_args(argv)
    if args.command == "run":
        try:
            ReviewConfig(**{key: value for key, value in vars(args).items() if key != "command"})
        except InputError as error:
            parser.error(str(error))
    return args


def main(argv=None) -> int:
    """선택한 작업을 실행하고 결과를 안내하며, 민감한 SDK 예외 원문은 출력하지 않는다."""
    args = parse_args(argv)
    options = {key: value for key, value in vars(args).items() if key != "command"}
    try:
        if args.command == "compare":
            from .comparison import compare_files
            compare_files(**options)
            return 0
        from .workflow import run_review
        outcome = asyncio.run(run_review(ReviewConfig(**options)))
        print(f"검토 결과: {outcome.output}")
        counts = outcome.counts
        print(f"완료 {counts['completed']} / 추가 검토 {counts['needs_review']} / "
              f"실패 {counts['failed']} / 미처리 {counts['not_processed']}")
        return outcome.exit_code
    except (InputError, FileNotFoundError) as error:
        print(f"실행 중단: {error}")
    except KeyboardInterrupt:
        print("작업을 중단했습니다.")
        return 130
    except Exception as error:
        print(f"실행 중단 ({type(error).__name__}).")
    return 1
