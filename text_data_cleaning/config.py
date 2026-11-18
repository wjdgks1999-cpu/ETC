"""정제 작업의 설정·프롬프트·환경 값을 실행 시에만 읽는다."""

from dataclasses import asdict, dataclass
import codecs
import hashlib
import json
import math
import os
from pathlib import Path


class CleaningError(Exception):
    """원문이나 비밀값 없이 사용자에게 전달할 실행 오류다."""


DEFAULT_MODEL = "gpt-5.6-luna"


@dataclass(frozen=True)
class Settings:
    """선택한 정제 방식과 실제 실행에 사용할 설정을 보관한다."""

    mode: str
    column: str
    encoding: str
    sheet: str | int
    model: str
    timeout: float
    prompt: str

    def fingerprint(self) -> str:
        """재개 시 정제 방식·입력 설정·모델·프롬프트가 같은지 확인한다."""
        payload = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def required_text(value: object, name: str) -> str:
    """필수 문자열을 검증하며 오류 메시지에 입력값을 포함하지 않는다."""
    if not isinstance(value, str) or not value.strip():
        raise CleaningError(f"{name}에는 비어 있지 않은 문자열이 필요합니다.")
    return value


def environment_value(name: str, env_file: str | Path | None = None) -> str:
    """환경 변수를 우선하고 명시한 환경 파일만 읽으며 프로세스 환경을 바꾸지 않는다."""
    value = os.environ.get(name, "").strip()
    if value or env_file is None:
        return value
    from dotenv import dotenv_values

    if not Path(env_file).is_file():
        raise CleaningError("지정한 환경 파일이 없습니다.")
    return (dotenv_values(env_file, encoding="utf-8", interpolate=False).get(name) or "").strip()


def read_api_key(env_file: str | Path | None = None) -> str:
    """실제 요청이 필요한 시점에만 키를 확인하고 없는 경우 중단한다."""
    key = environment_value("OPENAI_API_KEY", env_file)
    if not key:
        raise CleaningError("정제할 본문이 있습니다. OPENAI_API_KEY를 설정하거나 --env-file을 지정하세요.")
    return key


def load_settings(mode: str, config_path: str | Path | None = None,
                  env_file: str | Path | None = None) -> Settings:
    """기본값·JSON·모델 환경 설정을 결합하고 사용자 프롬프트를 읽는다."""
    if mode not in ("html", "privacy"):
        raise CleaningError("정제 방식은 html 또는 privacy여야 합니다.")
    raw = {}
    base = Path(__file__).parent
    if config_path is not None:
        path = Path(config_path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raise CleaningError("설정 JSON 파일을 읽을 수 없습니다.") from None
        base = path.parent
    allowed = {"column", "encoding", "sheet", "model", "timeout", "prompt_path"}
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise CleaningError("설정 형식이 잘못되었거나 지원하지 않는 설정 항목이 있습니다.")
    column = required_text(raw.get("column", "내용"), "column")
    encoding = required_text(raw.get("encoding", "cp949"), "encoding")
    try:
        codecs.lookup(encoding)
    except LookupError:
        raise CleaningError("지원하지 않는 CSV 인코딩입니다.") from None
    sheet = raw.get("sheet", 0)
    if (type(sheet) is not int or sheet < 0) and (not isinstance(sheet, str) or not sheet):
        raise CleaningError("sheet는 0부터 시작하는 번호 또는 시트 이름이어야 합니다.")
    model = (required_text(raw["model"], "model") if "model" in raw
             else environment_value("OPENAI_MODEL", env_file) or DEFAULT_MODEL)
    timeout = raw.get("timeout", 60)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise CleaningError("timeout은 양의 초 단위 숫자여야 합니다.")
    prompt_path = (base / required_text(raw["prompt_path"], "prompt_path") if "prompt_path" in raw
                   else Path(__file__).parent / "prompts" / f"{mode}.md")
    try:
        prompt = required_text(prompt_path.read_text(encoding="utf-8-sig"), "프롬프트")
    except OSError:
        raise CleaningError("프롬프트 파일을 읽을 수 없습니다.") from None
    return Settings(mode, column, encoding, sheet, model, float(timeout), prompt)
