"""모델 입력 항목과 작성·검수 결과의 자료형을 정의한다."""

from typing import Literal
from pydantic import BaseModel, ConfigDict

INPUT_COLUMNS = [
    "테이블 한글명", "테이블 영문명", "컬럼명(한글)", "컬럼명(영문)", "데이터타입",
]


CONTEXT_COLUMNS = {
    "information_system_name": "정보시스템명",
    "logical_db_name": "논리DB명",
}


class InputError(ValueError):
    """외부 SDK 예외와 구분하여 안전하게 표시할 수 있는 입력 오류."""


class ExclusionResult(BaseModel):
    """초안과 최종 결과에 공통으로 사용하는 JSON 형식."""

    model_config = ConfigDict(extra="forbid", strict=True)

    table_name: str
    exclusion_code: Literal["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"] | None
    exclusion_reason: str
    review_required: bool
    review_comment: str


class ReviewResult(BaseModel):
    """교정이 필요한 명백한 오류만 반환한다. 빈 목록이면 검수 통과."""

    model_config = ConfigDict(extra="forbid", strict=True)

    issues: list[str]
