"""설문별 질문·입력 컬럼·분류 기준을 실행 시에만 읽는다."""

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
from string import Formatter


class SurveyError(Exception):
    """응답 원문이나 비밀값 없이 사용자에게 전달할 실행 오류다."""


GENERAL_CATEGORIES = (
    "홍보", "신규개방", "데이터 형식", "콘텐츠", "품질 및 업데이트", "서비스 편의성", "기타",
)
AI_CATEGORIES = (
    "상담 기록 및 결과 데이터", "유형별 사례·대응 매뉴얼 및 판례 정보",
    "교육자료 및 예방 활동 자료", "피해자 지원 시설·기관 정보", "음성비서·챗봇 서비스 데이터",
    "여성폭력 발생 및 신고 통계 데이터", "인권 일반 정보", "교통·위치 정보", "기타",
)


@dataclass(frozen=True)
class Settings:
    """한 설문 문항의 설정과 실제 사용한 프롬프트를 보관한다."""

    mode: str
    question: str
    answer_column: str
    id_column: str | None
    sheet: str | int
    model: str
    timeout: float
    categories: tuple[str, ...]
    prompt: str

    def fingerprint(self) -> str:
        """재개 시 입력 설정·분류 기준·질문·프롬프트의 일치를 확인한다."""
        from dataclasses import asdict

        payload = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def required_text(value: object, field: str) -> str:
    """필수 문자열을 검증하며 오류에 입력값 자체를 포함하지 않는다."""
    if not isinstance(value, str) or not value.strip():
        raise SurveyError(f"설정의 {field}에는 비어 있지 않은 문자열이 필요합니다.")
    return value


def load_settings(path: str | Path) -> Settings:
    """JSON 설정과 프롬프트를 읽고 범주 및 템플릿의 일관성을 검사한다."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise SurveyError("설정 JSON 파일을 읽을 수 없습니다.") from None
    allowed = {"mode", "question", "answer_column", "id_column", "sheet", "model",
               "timeout", "categories", "prompt_path"}
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise SurveyError("설정 형식이 잘못되었거나 지원하지 않는 설정 항목이 있습니다.")
    mode = raw.get("mode", "general")
    if mode not in ("general", "ai"):
        raise SurveyError("mode는 general 또는 ai여야 합니다.")
    question = required_text(raw.get("question"), "question")
    answer_column = required_text(raw.get("answer_column"), "answer_column")
    id_column = raw.get("id_column")
    if id_column is not None:
        required_text(id_column, "id_column")
    sheet = raw.get("sheet", 0)
    if (type(sheet) is not int or sheet < 0) and (not isinstance(sheet, str) or not sheet):
        raise SurveyError("sheet는 0부터 시작하는 번호 또는 시트 이름이어야 합니다.")
    model = required_text(raw.get("model", "gpt-4o-mini"), "model")
    timeout = raw.get("timeout", 60)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise SurveyError("timeout은 양의 초 단위 숫자여야 합니다.")
    defaults = GENERAL_CATEGORIES if mode == "general" else AI_CATEGORIES
    categories = raw.get("categories", list(defaults))
    if (not isinstance(categories, list) or not categories
            or any(not isinstance(x, str) or not x.strip() or x != x.strip()
                   or any(c in x for c in ",\n\r:") for x in categories)
            or len(set(categories)) != len(categories)):
        raise SurveyError("범주는 중복 없는 문자열 목록이어야 하며 쉼표·콜론·줄바꿈을 포함할 수 없습니다.")
    default_prompt = "prompt.md" if mode == "general" else "prompt_ai.md"
    if "prompt_path" in raw:
        prompt_path = path.parent / required_text(raw["prompt_path"], "prompt_path")
    else:
        prompt_path = Path(__file__).parent / default_prompt
    try:
        prompt = prompt_path.read_text(encoding="utf-8-sig")
        fields = [(name, spec, conversion) for _, name, spec, conversion in Formatter().parse(prompt)
                  if name is not None]
    except (OSError, ValueError):
        raise SurveyError("프롬프트 파일을 읽을 수 없거나 템플릿 형식이 잘못되었습니다.") from None
    if {name for name, _, _ in fields} != {"question", "answer"} or any(
            spec or conversion for _, spec, conversion in fields):
        raise SurveyError("프롬프트 변수는 {question}과 {answer}만 사용해야 합니다.")
    guide_names = re.findall(r"^-\s+([^:\r\n]+?)\s*:\s*.+$", prompt, re.MULTILINE)
    if guide_names != categories:
        raise SurveyError("프롬프트의 '- 범주 : 설명' 목록과 설정 categories의 순서·내용이 다릅니다.")
    return Settings(mode, question, answer_column, id_column, sheet, model,
                    float(timeout), tuple(categories), prompt)


def read_api_key(env_file: str | Path | None = None) -> str:
    """환경 변수를 우선 사용하고 명시한 env 파일만 읽으며 환경을 변경하지 않는다."""
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key and env_file is not None:
        from dotenv import dotenv_values

        if not Path(env_file).is_file():
            raise SurveyError("지정한 환경 파일이 없습니다.")
        key = (dotenv_values(env_file, encoding="utf-8", interpolate=False).get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise SurveyError("분류할 응답이 있습니다. OPENAI_API_KEY를 설정하거나 --env-file을 지정하세요.")
    return key
