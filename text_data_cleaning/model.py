"""HTML 제거와 개인정보 문구 삭제의 지시·출력 구조를 구분해 모델에 전달한다."""

from typing import Callable

from config import Settings
from storage import valid_excel_text


class InvalidResult(Exception):
    """누락·잘못된 형식 등 저장할 수 없는 정제 결과다."""


def validate_result(value: object) -> str:
    """문자열 결과만 허용하고 Excel 저장 시 잘리거나 손상될 값은 거부한다."""
    if not isinstance(value, str) or not valid_excel_text(value):
        raise InvalidResult("정제 결과의 형식 또는 길이가 올바르지 않습니다.")
    return value


def build_schema(mode: str):
    """기존 두 필드명을 유지하며 필수 문자열·추가 필드 금지를 적용한다."""
    from pydantic import ConfigDict, Field, StrictStr, create_model

    field = "content" if mode == "html" else "Preprocess_Content"
    description = "내용" if mode == "html" else "개인정보를 삭제한 공고문 정보"
    schema = create_model("ContentInfo", __config__=ConfigDict(extra="forbid"),
                          **{field: (StrictStr, Field(description=description))})
    schema.__doc__ = "필수 문자열인 정제 결과를 담는 구조다."
    return schema, field


def build_cleaner(settings: Settings, api_key: str, *, http_client=None) -> Callable[[str], str]:
    """작업당 체인을 한 번 생성하고 실제 요청은 반환한 함수 호출 시 수행한다."""
    from langchain_core.exceptions import OutputParserException
    from langchain_core.messages import SystemMessage
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_openai import ChatOpenAI
    from langsmith import tracing_context
    from pydantic import ValidationError

    schema, field = build_schema(settings.mode)
    options = {"model": settings.model, "api_key": api_key, "timeout": settings.timeout,
               "max_retries": 0, "base_url": "https://api.openai.com/v1"}
    if http_client is not None:
        options["http_client"] = http_client
    llm = ChatOpenAI(**options)
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content=settings.prompt), ("human", "{target_contents}"),
    ])
    chain = prompt | llm.with_structured_output(schema, method="function_calling")

    def clean_text(contents: str) -> str:
        """지시와 분리한 본문을 한 번 전송하고 외부 추적 없이 구조화 결과를 검증한다."""
        try:
            with tracing_context(enabled=False):
                result = chain.invoke({"target_contents": contents})
            if not isinstance(result, schema):
                raise InvalidResult("구조화된 정제 결과가 없습니다.")
            return validate_result(getattr(result, field))
        except (ValidationError, OutputParserException):
            raise InvalidResult("구조화된 정제 결과가 올바르지 않습니다.") from None

    return clean_text
