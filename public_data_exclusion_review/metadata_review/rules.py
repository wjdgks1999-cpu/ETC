"""고정 제외 규칙과 작성 결과의 형식·일관성 검증을 담당한다."""

import json
import re
from .schemas import ExclusionResult


def fixed_result(table_name: str, column_count: int) -> ExclusionResult | None:
    """컬럼 2개 이하는 행 수와 무관하게 합의된 코드·사유로 제외 처리한다."""
    if column_count > 2:
        return None
    return ExclusionResult(
        table_name=table_name, exclusion_code="9",
        exclusion_reason="3열 5행 미만 테이블", review_required=False,
        review_comment=f"컬럼 {column_count}개로 사용자 지정 제외 규칙 적용",
    )

MAX_CORRECTIONS = 2


UNCERTAIN_REASON = re.compile(
    r"(?:확인|검토)(?:이|가|을|를)?\s*(?:할\s*필요|필요|해야|전(?=\s|에|까지|의|$)|이전|후(?=\s|에|$)|될\s*때|되기\s*전|되지)|"
    r"추정(?:되어|되므로|됨|되며)|조건부(?:로)?\s*(?:제외|개방|선정)|"
    # '정보이므로/정보이며' 안의 '보이므로/보이며'를 추측 표현으로 오인하지 않는다.
    r"가능성|\b보이(?:는|며|므로|고)|\b보여|(?:할|될|일|있을)\s*수\s*있"
)


OPEN_RECOMMENDATION = re.compile(
    r"(?:개방|공개)(?:을|를)?\s*(?:해야|하여야|(?:권고|추천|결정|필요)(?:함|합니다|한다|하다|하겠습니다))|"
    r"(?:개방|공개)\s*대상(?:임|이다)"
)


def normalize_result(result: ExclusionResult, columns_df: str) -> ExclusionResult:
    """실제 컬럼명은 보존하고, 사유의 공백·줄바꿈·가운뎃점·종결 마침표만 정리한다."""
    names = sorted({
        row[key] for row in json.loads(columns_df)
        for key in ("컬럼명(한글)", "컬럼명(영문)")
        if isinstance(row.get(key), str) and row[key]
    }, key=lambda name: (-len(name), name))
    # 긴 이름부터 분리하여 컬럼명 내부의 기호와 공백은 그대로 둔다.
    pattern = "(" + "|".join(map(re.escape, names)) + ")" if names else None
    parts = re.split(pattern, result.exclusion_reason) if pattern else [result.exclusion_reason]
    for index in range(0, len(parts), 2):
        text = re.sub(r"\s+", " ", parts[index].replace("·", ", "))
        if index == len(parts) - 1:
            text = re.sub(r"(?<=제외)[.。]+$", "", text.rstrip())
        parts[index] = text
    return result.model_copy(update={"exclusion_reason": "".join(parts).strip()})


def validate_final(result: ExclusionResult, table_name: str) -> None:
    """명백한 금지 표현과 결과 필드의 일관성을 검사하고 오류를 모아 알린다."""
    problems = []
    if result.table_name != table_name:
        problems.append("table_name이 원본 테이블명과 다름")
    if result.exclusion_code == "10":
        problems.append("컬럼 스키마만으로 개방 완료 사실을 확인할 수 없으므로 10은 선정할 수 없음")
    reason = result.exclusion_reason
    if reason and (reason != reason.strip() or not reason.endswith("제외")):
        problems.append("사유는 앞뒤 공백 없이 '제외'로 끝나야 함")
    if UNCERTAIN_REASON.search(reason):
        problems.append("추측·확인·검토 필요성은 제외 사유의 근거가 될 수 없음. 검토 의견으로 옮기고 원본 근거로 다시 작성해야 함")
    if result.exclusion_code is None and (reason or not result.review_required):
        problems.append("코드가 null이면 사유는 빈 문자열, review_required는 true여야 함")
    if result.exclusion_code is not None and not reason:
        problems.append("제외코드를 선정했다면 명확한 제외 사유를 반드시 작성해야 함")
    if OPEN_RECOMMENDATION.search(reason + " " + result.review_comment):
        problems.append("이 작업에서 개방을 권고하거나 결정할 수 없음. 제외 근거가 없으면 판단 보류로 작성해야 함")
    if not result.review_comment.strip():
        problems.append("검토 의견이 비어 있음")
    if problems:
        raise ValueError("; ".join(problems))
