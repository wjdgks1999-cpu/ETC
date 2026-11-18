"""두 분류 방식의 차이를 유지하며 행별 처리·체크포인트·재개를 관리한다."""

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Callable

from config import Settings, SurveyError, read_api_key
from storage import Table, check_new_path, output_lock, read_table, source_rows, write_workbook


RESULT_COLUMNS = ["category", "status", "error_code"]
STATES = {"pending", "completed", "skipped", "error"}


class InvalidResult(Exception):
    """허용한 분류 기준을 만족하지 않는 모델 결과다."""


def validate_labels(labels: object, settings: Settings) -> list[str]:
    """범주 목록의 개수·허용값·중복을 검사하고 자동 보정하지 않는다."""
    if (not isinstance(labels, list) or not labels
            or any(not isinstance(x, str) or x not in settings.categories for x in labels)
            or len(set(labels)) != len(labels)
            or (settings.mode == "ai" and len(labels) != 1)):
        raise InvalidResult("분류 결과가 허용한 범주 또는 선택 개수와 다릅니다.")
    return labels


def parse_labels(value: object, settings: Settings) -> list[str]:
    """검토된 Excel의 쉼표 구분 범주를 읽고 단일·복수 분류 규칙을 확인한다."""
    if not isinstance(value, str) or not value.strip():
        raise InvalidResult("분류값이 비어 있습니다.")
    return validate_labels([part.strip() for part in value.split(",")], settings)


def build_schema(settings: Settings):
    """현재 분류체계의 허용 범주를 열거한 Pydantic 출력 모델을 만든다."""
    from enum import Enum
    from pydantic import ConfigDict, Field, create_model

    choices = Enum("CategoryValue", {f"C{i}": value for i, value in enumerate(settings.categories)}, type=str)
    single = create_model(
        "Category", __config__=ConfigDict(extra="forbid"),
        category=(choices, Field(description="답변의 주제")),
    )
    single.__doc__ = "허용한 범주 중 하나를 담는 분류 결과다."
    if settings.mode == "ai":
        return single
    multiple = create_model(
        "Categories", __config__=ConfigDict(extra="forbid"),
        categories=(list[single], Field(min_length=1, description="답변의 주제 리스트")),
    )
    multiple.__doc__ = "한 응답에 포함된 하나 이상의 주제를 담는 분류 결과다."
    return multiple


def build_classifier(settings: Settings, api_key: str, *, http_client=None) -> Callable[[str], list[str]]:
    """모델과 체인을 한 번 만들고 행별 호출 함수를 반환한다. 생성 시 요청하지 않는다."""
    from langchain_core.prompts import PromptTemplate
    from langchain_core.exceptions import OutputParserException
    from langchain_openai import ChatOpenAI
    from langsmith import tracing_context
    from pydantic import ValidationError

    schema = build_schema(settings)
    options = {"model": settings.model, "api_key": api_key, "timeout": settings.timeout,
               "max_retries": 0, "base_url": "https://api.openai.com/v1"}
    if http_client is not None:
        options["http_client"] = http_client
    model = ChatOpenAI(**options)
    chain = (PromptTemplate.from_template(settings.prompt)
             | model.with_structured_output(schema, method="function_calling"))

    def classify(answer: str) -> list[str]:
        """질문과 응답을 한 번 전송하고 검증된 범주만 반환하며 외부 추적을 끈다."""
        try:
            with tracing_context(enabled=False):
                result = chain.invoke({"question": settings.question, "answer": answer})
            if not isinstance(result, schema):
                raise InvalidResult("구조화된 분류 결과가 없습니다.")
            data = result.model_dump(mode="json")
            labels = ([item["category"] for item in data["categories"]]
                      if settings.mode == "general" else [data["category"]])
            return validate_labels(labels, settings)
        except (ValidationError, OutputParserException):
            raise InvalidResult("구조화된 분류 결과가 올바르지 않습니다.") from None

    return classify


def prepare_responses(table: Table, settings: Settings) -> tuple[list[str], list[list]]:
    """원본 컬럼·행 순서를 보존하고 응답이 빈 행만 건너뛰기 상태로 표시한다."""
    required = [settings.answer_column] + ([settings.id_column] if settings.id_column else [])
    if any(column not in table.headers for column in required):
        raise SurveyError("설정한 응답 또는 식별자 컬럼이 입력에 없습니다.")
    if any(column in table.headers for column in RESULT_COLUMNS):
        raise SurveyError("원본에 결과용 컬럼(category, status, error_code)이 이미 있습니다.")
    headers = list(table.headers)
    add_source = "source_row" not in headers
    if add_source:
        headers.append("source_row")
    answer_index = table.headers.index(settings.answer_column)
    rows = []
    for number, original in zip(source_rows(table), table.rows):
        answer = original[answer_index]
        empty = answer is None or (isinstance(answer, str) and not answer.strip())
        rows.append(list(original) + ([number] if add_source else [])
                    + [None, "skipped" if empty else "pending", None])
    return headers + RESULT_COLUMNS, rows


def run_metadata(table: Table, settings: Settings) -> dict:
    """재개 비교와 결과 해석에 필요한 비밀값 없는 메타데이터를 만든다."""
    return {"schema_version": 1, "input_sha256": table.digest,
            "config_sha256": settings.fingerprint(), "mode": settings.mode,
            "model": settings.model, "categories": list(settings.categories),
            "sheet": table.sheet, "row_count": len(table.rows)}


def save_checkpoint(path: Path, headers: list[str], rows: list[list], metadata: dict,
                    *, replace: bool) -> None:
    """응답과 실행 식별정보를 같은 파일에 저장해 서로 다른 시점이 섞이지 않게 한다."""
    meta_rows = [[key, json.dumps(value, ensure_ascii=False)] for key, value in metadata.items()]
    write_workbook(path, {"responses": [headers] + rows, "run": [["key", "value"]] + meta_rows},
                   replace=replace)


def load_checkpoint(path: Path, headers: list[str], initial: list[list], metadata: dict,
                    settings: Settings) -> list[list]:
    """원본·설정·행 대응이 같은 결과만 재개하며 완료된 수동 수정 분류값도 검증한다."""
    try:
        saved = read_table(path, "responses")
        meta = read_table(path, "run")
        if meta.headers != ["key", "value"] or len({row[0] for row in meta.rows}) != len(meta.rows):
            raise ValueError
        saved_metadata = {key: json.loads(value) for key, value in meta.rows}
        if saved_metadata != metadata or saved.headers != headers or len(saved.rows) != len(initial):
            raise ValueError
        for row, original in zip(saved.rows, initial):
            if row[:-3] != original[:-3] or row[-2] not in STATES:
                raise ValueError
            category, status, error = row[-3:]
            if original[-2] == "skipped":
                if status != "skipped" or category is not None or error is not None:
                    raise ValueError
            elif status == "completed":
                parse_labels(category, settings)
                if error is not None:
                    raise ValueError
            elif status in ("pending", "error"):
                if category is not None or (status == "pending" and error is not None):
                    raise ValueError
                if status == "error" and error not in ("API_ERROR", "INVALID_RESULT"):
                    raise ValueError
            else:
                raise ValueError
        return saved.rows
    except (SurveyError, ValueError, TypeError, InvalidResult):
        raise SurveyError("재개할 수 없습니다. 입력·설정·체크포인트의 행 또는 상태가 일치하지 않습니다.") from None


def classify_file(input_path: str | Path, output_path: str | Path, settings: Settings,
                  *, resume: bool = False, env_file: str | Path | None = None,
                  classifier: Callable[[str], list[str]] | None = None,
                  progress: Callable[[int, int], None] | None = None) -> dict[str, int]:
    """미완료 응답을 순차 처리하며 매 행 저장하고 첫 실패에서 멈춰 명시적 재개를 기다린다."""
    output = Path(output_path)
    if output.suffix.lower() != ".xlsx" or output.resolve() == Path(input_path).resolve():
        raise SurveyError("분류 결과는 원본과 다른 .xlsx 경로에 저장해야 합니다.")
    if not resume:
        check_new_path(output)
    elif not output.is_file() or output.is_symlink():
        raise SurveyError("재개할 결과 파일이 없습니다.")
    table = read_table(input_path, settings.sheet)
    headers, initial = prepare_responses(table, settings)
    metadata = run_metadata(table, settings)
    with output_lock(output):
        checkpoint_digest = hashlib.sha256(output.read_bytes()).hexdigest() if resume else None
        rows = load_checkpoint(output, headers, initial, metadata, settings) if resume else initial
        if resume and hashlib.sha256(output.read_bytes()).hexdigest() != checkpoint_digest:
            raise SurveyError("체크포인트를 읽는 중 파일이 변경되었습니다. 다시 확인하세요.")
        pending = [i for i, row in enumerate(rows) if row[-2] in ("pending", "error")]
        if pending and classifier is None:
            classifier = build_classifier(settings, read_api_key(env_file))
        if not resume:
            save_checkpoint(output, headers, rows, metadata, replace=False)
            checkpoint_digest = hashlib.sha256(output.read_bytes()).hexdigest()
        answer_index = headers.index(settings.answer_column)
        for ordinal, index in enumerate(pending, 1):
            row = rows[index]
            try:
                labels = validate_labels(classifier(str(row[answer_index])), settings)
                row[-3:] = [", ".join(labels), "completed", None]
            except InvalidResult:
                row[-3:] = [None, "error", "INVALID_RESULT"]
            except Exception:
                # SDK 예외에는 응답 원문·요청 정보가 포함될 수 있어 저장하거나 출력하지 않는다.
                row[-3:] = [None, "error", "API_ERROR"]
            if hashlib.sha256(output.read_bytes()).hexdigest() != checkpoint_digest:
                raise SurveyError("처리 중 결과 파일이 외부에서 변경되었습니다. 덮어쓰지 않고 중단합니다.")
            save_checkpoint(output, headers, rows, metadata, replace=True)
            checkpoint_digest = hashlib.sha256(output.read_bytes()).hexdigest()
            if progress is not None:
                progress(ordinal, len(pending))
            if row[-2] == "error":
                break
        return dict(Counter(row[-2] for row in rows))
