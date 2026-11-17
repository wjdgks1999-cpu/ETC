"""문서 파싱 명령의 설정과 실행 오류를 정의한다."""

from dataclasses import dataclass
import math
import os
from pathlib import Path

API_URL = "https://api.upstage.ai/v1/document-digitization"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
SUPPORTED_SUFFIXES = {".pdf", ".hwp", ".hwpx", ".docx", ".pptx", ".xlsx",
                      ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".heic"}


class ParseError(ValueError):
    """문서 내용과 비밀값을 포함하지 않는 사용자용 실행 오류다."""


@dataclass(frozen=True)
class Settings:
    """비밀값을 제외한 입력·출력·요청 옵션을 보관한다."""

    input_path: Path
    output_path: Path
    env_file: Path | None = None
    model: str = "document-parse"
    ocr: str = "force"
    timeout: float = 300.0


def validate_settings(settings):
    """파일·출력 충돌·요청 옵션을 확인하고 절대 경로 설정을 반환한다."""
    source = Path(settings.input_path).resolve()
    output = Path(settings.output_path).absolute()
    if not source.is_file():
        raise ParseError("입력 파일이 없거나 일반 파일이 아닙니다.")
    if source.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ParseError("지원하지 않는 문서 확장자입니다.")
    if source.stat().st_size == 0:
        raise ParseError("입력 파일이 비어 있습니다.")
    if os.path.lexists(output):
        raise ParseError("출력 경로가 이미 존재합니다. 새 폴더 경로를 지정하세요.")
    output = output.resolve()
    for parent in output.parents:
        if parent.exists():
            if not parent.is_dir():
                raise ParseError("출력 경로의 상위 경로가 폴더가 아닙니다.")
            break
    if (not isinstance(settings.model, str) or not settings.model.strip()
            or any(char.isspace() for char in settings.model)):
        raise ParseError("공백 없는 모델 이름을 지정하세요.")
    if settings.ocr not in {"force", "auto"}:
        raise ParseError("OCR 설정은 force 또는 auto여야 합니다.")
    if (type(settings.timeout) not in (int, float) or not math.isfinite(settings.timeout)
            or settings.timeout <= 0):
        raise ParseError("요청 제한 시간은 0보다 큰 유한한 초 단위 값이어야 합니다.")
    env_file = Path(settings.env_file).resolve() if settings.env_file is not None else None
    if env_file is not None and not env_file.is_file():
        raise ParseError("지정한 환경 변수 파일이 없습니다.")
    return Settings(source, output, env_file, settings.model, settings.ocr, float(settings.timeout))


def load_api_key(env_file=None):
    """실행 시에만 환경 변수 또는 명시한 파일에서 키를 읽고 환경은 변경하지 않는다."""
    key = os.environ.get("UPSTAGE_API_KEY")
    if not key and env_file is not None:
        from dotenv import dotenv_values

        try:
            key = dotenv_values(env_file, encoding="utf-8-sig", interpolate=False).get("UPSTAGE_API_KEY")
        except (OSError, UnicodeError) as error:
            raise ParseError("환경 변수 파일을 UTF-8로 읽을 수 없습니다.") from error
    if not isinstance(key, str) or not key.strip():
        raise ParseError("UPSTAGE_API_KEY를 환경 변수 또는 --env-file로 설정하세요.")
    key = key.strip()
    if any(char.isspace() for char in key):
        raise ParseError("API 키에 공백이나 줄바꿈이 포함되어 있습니다.")
    return key
