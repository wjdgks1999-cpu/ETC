"""문서 파싱을 실행하는 명령 진입점이다."""

import argparse
import asyncio
from pathlib import Path
import sys

from config import ParseError, Settings, load_api_key, validate_settings


def build_parser():
    """문서·새 출력 폴더·선택 요청 옵션을 명령 인수로 정의한다."""
    parser = argparse.ArgumentParser(description="기관 문서를 페이지별 Markdown과 검토 명세로 변환")
    parser.add_argument("--input", required=True, type=Path, help="입력 문서 파일")
    parser.add_argument("--output", required=True, type=Path, help="아직 존재하지 않는 결과 폴더")
    parser.add_argument("--env-file", type=Path, help="API 키가 있는 UTF-8 환경 변수 파일")
    parser.add_argument("--model", default="document-parse", help="Upstage 모델 이름")
    parser.add_argument("--ocr", choices=["force", "auto"], default="force", help="OCR 적용 방식")
    parser.add_argument("--timeout", type=float, default=300, help="요청 1건의 제한 시간(초)")
    return parser


def show_progress(current, total):
    """문서 내용이나 비밀값 없이 요청 진행 건수만 알린다."""
    print(f"파싱 요청 {current}/{total}", flush=True)


async def run(settings, transport=None, api_key=None):
    """입력·출력을 검사한 뒤 요청과 저장을 순서대로 수행한다."""
    from client import parse_document, read_source
    from storage import save_result

    settings = validate_settings(settings)
    source = read_source(settings.input_path)
    key = load_api_key(settings.env_file) if api_key is None else api_key
    result = await parse_document(source, settings, key, transport=transport, progress=show_progress)
    manifest = save_result(source, result, settings)
    print(f"페이지 파일 {manifest['written_page_count']}개와 manifest.json 저장 완료.")
    if manifest["status"] == "review_required":
        print(f"검토 항목 {len(manifest['issues'])}개가 있습니다. manifest.json을 확인하세요.")
        return 1
    return 0


def main(argv=None):
    """명령 오류를 안전한 메시지로 출력하고 성공·검토 필요·실패를 구분한다."""
    args = build_parser().parse_args(argv)
    settings = Settings(args.input, args.output, args.env_file, args.model, args.ocr, args.timeout)
    try:
        return asyncio.run(run(settings))
    except ParseError as error:
        print(f"오류: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("작업을 중단했습니다.", file=sys.stderr)
        return 130
    except Exception as error:
        # 원격 오류 본문이나 예외에 포함된 문서 내용·키를 출력하지 않는다.
        print(f"오류: 작업을 완료하지 못했습니다({type(error).__name__}). "
              "입출력 권한과 설치 환경을 확인하세요.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
