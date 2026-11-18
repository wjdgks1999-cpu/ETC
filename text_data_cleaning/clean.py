"""HTML 제거와 개인정보 문구 삭제를 명시적으로 실행하는 명령 진입점이다."""

import argparse
import sys

from config import CleaningError, load_settings


def build_parser() -> argparse.ArgumentParser:
    """정제 방식·입출력·설정·재개 옵션을 정의하며 파일이나 키를 읽지 않는다."""
    parser = argparse.ArgumentParser(description="텍스트 컬럼의 HTML 제거·개인정보 문구 삭제")
    modes = parser.add_subparsers(dest="mode", required=True)
    for name, description in (("html", "HTML 양식 제거"), ("privacy", "개인정보 포함 문구 삭제")):
        command = modes.add_parser(name, help=description)
        command.add_argument("--input", required=True, help="입력 CSV 또는 Excel 파일")
        command.add_argument("--output", required=True, help="새 결과 .xlsx 경로")
        command.add_argument("--config", help="컬럼·인코딩·시트·모델·프롬프트 설정 JSON")
        command.add_argument("--env-file", help="명시적으로 읽을 환경 파일")
        command.add_argument("--resume", action="store_true", help="같은 입력·설정의 미완료 행만 재개")
    return parser


def print_progress(done: int, total: int) -> None:
    """원문·식별자·비밀값 없이 이번 실행의 처리 건수만 출력한다."""
    print(f"진행: {done}/{total}", flush=True)


def main(argv: list[str] | None = None) -> int:
    """처리 완료 0·미완료 또는 검토 필요 1·실행 실패 2를 반환한다."""
    args = build_parser().parse_args(argv)
    try:
        from workflow import clean_file

        settings = load_settings(args.mode, args.config, args.env_file)
        states = clean_file(args.input, args.output, settings, resume=args.resume,
                            env_file=args.env_file, progress=print_progress)
        print("처리 결과: " + ", ".join(f"{name}={states.get(name, 0)}" for name in
                                     ("completed", "skipped", "review_required", "error", "pending")))
        return 1 if any(states.get(name, 0) for name in ("review_required", "error", "pending")) else 0
    except CleaningError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("중단했습니다. 마지막 저장 결과에서 --resume으로 재개할 수 있습니다.", file=sys.stderr)
        return 2
    except Exception:
        print("실행에 실패했습니다. 입력·의존성·출력 권한 및 파일 사용 여부를 확인하세요.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
