"""원본 행을 유지하면서 정제·행별 저장·실패 후 재개를 수행한다."""

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Callable

from config import CleaningError, Settings, read_api_key
from model import InvalidResult, build_cleaner, validate_result
from storage import (FORMAT_ID, PROCESSING_HEADERS, Table, blank, check_new_path,
                     load_checkpoint, output_lock, read_input, write_workbook)


def prepare_records(table: Table, settings: Settings) -> list[list]:
    """원본 행에 대응하는 상태를 만들고 비문자열 본문은 요청 전에 거부한다."""
    if settings.column not in table.headers:
        raise CleaningError("지정한 본문 컬럼이 입력에 없습니다.")
    column = table.headers.index(settings.column)
    records = []
    for number, row in zip(table.source_rows, table.rows):
        value = row[column]
        if value is not None and not isinstance(value, str):
            raise CleaningError("본문 컬럼에 문자열이 아닌 값이 있습니다. 입력 형식을 확인하세요.")
        records.append([number, "skipped" if blank(value) else "pending", None, None])
    return records


def metadata_for(table: Table, settings: Settings) -> dict:
    """비밀값과 원문을 넣지 않고 실행 식별정보를 구성한다."""
    return {"format": FORMAT_ID, "input_sha256": table.digest,
            "config_sha256": settings.fingerprint(), "mode": settings.mode,
            "model": settings.model, "column": settings.column,
            "source_sheet": table.sheet, "row_count": len(table.rows)}


def data_rows(table: Table, records: list[list], settings: Settings) -> list[list]:
    """정제된 행만 대상 컬럼을 바꾸고 실패·대기 행과 다른 컬럼의 원본 값은 유지한다."""
    column = table.headers.index(settings.column)
    rows = [list(row) for row in table.rows]
    for row, record in zip(rows, records):
        if record[1] in ("completed", "review_required"):
            row[column] = record[2]
    return rows


def save_checkpoint(path: Path, table: Table, records: list[list], settings: Settings,
                    metadata: dict, *, replace: bool) -> str:
    """데이터·처리 상태·실행 정보를 같은 Excel에 저장하고 확정한 파일 해시를 반환한다."""
    run_rows = [[key, json.dumps(value, ensure_ascii=False)] for key, value in metadata.items()]
    return write_workbook(path, {
        "data": [table.headers] + data_rows(table, records, settings),
        "processing": [PROCESSING_HEADERS] + records,
        "run": [["key", "value"]] + run_rows,
    }, replace=replace)


def comparable_rows(rows: list[list]) -> list[list]:
    """Excel이 빈 문자열을 빈 셀로 저장하는 차이만 비교 시 정규화한다."""
    return [[None if value == "" else value for value in row] for row in rows]


def resume_records(path: Path, table: Table, initial: list[list], settings: Settings,
                   metadata: dict) -> tuple[list[list], str]:
    """같은 원본·설정이며 결과가 임의 변경되지 않은 체크포인트만 재개한다."""
    checkpoint = load_checkpoint(path)
    if checkpoint.metadata != metadata or checkpoint.headers != table.headers:
        raise CleaningError("재개할 입력·설정·프롬프트 또는 컬럼 구성이 다릅니다.")
    if len(checkpoint.processing) != len(initial):
        raise CleaningError("체크포인트 행 수가 원본과 다릅니다.")
    for saved, original in zip(checkpoint.processing, initial):
        if saved[0] != original[0] or (saved[1] == "skipped") != (original[1] == "skipped"):
            raise CleaningError("체크포인트 원본 행 번호 또는 건너뛰기 상태가 다릅니다.")
    expected = data_rows(table, checkpoint.processing, settings)
    if comparable_rows(checkpoint.rows) != comparable_rows(expected):
        raise CleaningError("체크포인트의 데이터가 원본·정제 결과와 일치하지 않습니다.")
    return checkpoint.processing, checkpoint.digest


def check_unchanged(path: Path, expected_digest: str) -> None:
    """다른 작업이 결과를 수정했으면 덮어쓰지 않고 중단한다."""
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_digest:
        raise CleaningError("결과 파일이 다른 작업에서 변경되었습니다. 덮어쓰지 않고 중단합니다.")


def clean_file(input_path: str | Path, output_path: str | Path, settings: Settings,
               *, resume: bool = False, env_file: str | Path | None = None,
               cleaner: Callable[[str], str] | None = None,
               progress: Callable[[int, int], None] | None = None) -> dict[str, int]:
    """미완료 본문을 한 번씩 처리·저장하고 첫 오류에서 멈추며 빈 결과는 검토 대상으로 남긴다."""
    output = Path(output_path)
    if output.suffix.lower() != ".xlsx" or output.resolve() == Path(input_path).resolve():
        raise CleaningError("결과는 원본과 다른 .xlsx 경로에 저장해야 합니다.")
    if resume:
        if not output.is_file() or output.is_symlink():
            raise CleaningError("재개할 결과 파일이 없습니다.")
    else:
        check_new_path(output)
    table = read_input(input_path, settings)
    initial = prepare_records(table, settings)
    metadata = metadata_for(table, settings)
    with output_lock(output):
        if resume:
            records, expected_digest = resume_records(output, table, initial, settings, metadata)
        else:
            records = initial
        pending = [i for i, record in enumerate(records) if record[1] in ("pending", "error")]
        if pending and cleaner is None:
            cleaner = build_cleaner(settings, read_api_key(env_file))
        if not resume:
            expected_digest = save_checkpoint(output, table, records, settings, metadata, replace=False)
        check_unchanged(output, expected_digest)
        column = table.headers.index(settings.column)
        for ordinal, index in enumerate(pending, 1):
            check_unchanged(output, expected_digest)
            record = records[index]
            try:
                result = validate_result(cleaner(table.rows[index][column]))
                record[1:] = (["review_required", result, "EMPTY_RESULT"] if not result.strip()
                              else ["completed", result, None])
            except InvalidResult:
                record[1:] = ["error", None, "INVALID_RESULT"]
            except Exception:
                # 원격 오류에는 요청 본문이 섞일 수 있어 상세 내용을 출력·저장하지 않는다.
                record[1:] = ["error", None, "API_ERROR"]
            check_unchanged(output, expected_digest)
            expected_digest = save_checkpoint(output, table, records, settings, metadata, replace=True)
            if progress is not None:
                progress(ordinal, len(pending))
            if record[1] == "error":
                break
        return dict(Counter(record[1] for record in records))
