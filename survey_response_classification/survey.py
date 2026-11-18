"""설문 응답 추출·분류·집계를 명시적으로 실행하는 명령 진입점이다."""

import argparse
import sys

from config import SurveyError, load_settings


def sheet_value(value: str) -> int | str:
    """숫자 옵션은 0부터 시작하는 시트 번호로, 그 외는 시트 이름으로 해석한다."""
    return int(value) if value.isdecimal() else value


def build_parser() -> argparse.ArgumentParser:
    """입출력 경로와 작업별 옵션을 정의하며 파일·환경 변수를 읽지 않는다."""
    parser = argparse.ArgumentParser(description="설문 주관식 응답 추출·분류·집계")
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="선택 컬럼과 원본 행 번호 추출")
    classify = commands.add_parser("classify", help="일반 복수 또는 AI 단일 분류")
    summarize = commands.add_parser("summarize", help="검토된 분류 파일의 집계표·차트 저장")
    for command in (extract, classify, summarize):
        command.add_argument("--input", required=True, help="입력 .xlsx 경로")
        command.add_argument("--output", required=True, help="새 출력 경로(집계는 폴더)")
    extract.add_argument("--columns", required=True, nargs="+", help="유지할 컬럼 이름 목록")
    extract.add_argument("--sheet", type=sheet_value, default=0, help="시트 이름 또는 0부터 시작하는 번호")
    for command in (classify, summarize):
        command.add_argument("--config", required=True, help="설문 설정 JSON 경로")
    classify.add_argument("--resume", action="store_true", help="동일 작업의 미완료 행만 재개")
    classify.add_argument("--env-file", help="명시적으로 읽을 환경 파일")
    summarize.add_argument("--sheet", type=sheet_value, default=0, help="검토 파일 시트 이름 또는 번호")
    summarize.add_argument("--font", help="한국어 폰트 파일 경로")
    summarize.add_argument("--show", action="store_true", help="저장 시 그래프 창도 표시")
    return parser


def print_progress(done: int, total: int) -> None:
    """응답 원문과 식별자 없이 이번 실행의 진행 건수만 출력한다."""
    print(f"진행: {done}/{total}", flush=True)


def main(argv: list[str] | None = None) -> int:
    """명령을 실행하고 완료 0·미완료 분류 1·실행 실패 2를 반환한다."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "extract":
            from storage import extract_columns

            count = extract_columns(args.input, args.output, args.columns, args.sheet)
            print(f"추출 완료: {count}행")
            return 0
        settings = load_settings(args.config)
        if args.command == "classify":
            from labeling import classify_file

            states = classify_file(args.input, args.output, settings, resume=args.resume,
                                   env_file=args.env_file, progress=print_progress)
            print("처리 결과: " + ", ".join(f"{name}={states.get(name, 0)}"
                                         for name in ("completed", "skipped", "error", "pending")))
            return 1 if states.get("error", 0) or states.get("pending", 0) else 0
        from reporting import summarize_file

        summary = summarize_file(args.input, args.output, settings, sheet=args.sheet,
                                 font_path=args.font, show=args.show)
        print(f"집계 완료: 분류 응답 {summary.response_count}건, 범주 할당 {summary.assignment_count}건")
        return 0
    except SurveyError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("중단했습니다. 마지막으로 저장된 결과에서 --resume으로 재개할 수 있습니다.", file=sys.stderr)
        return 2
    except Exception:
        # 파일 경로·원문·SDK 오류 본문이 포함된 예외를 그대로 출력하지 않는다.
        print("실행에 실패했습니다. 입력·의존성·출력 권한 및 파일 사용 여부를 확인하세요.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
