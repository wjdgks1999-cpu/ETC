"""CSV·Excel의 셀 값과 행 대응을 보존하고 정제 체크포인트를 저장한다."""

from contextlib import contextmanager
import csv
from dataclasses import dataclass
import hashlib
from io import BytesIO, StringIO
import json
import math
import os
from pathlib import Path
import re
import tempfile

from config import CleaningError, Settings


FORMAT_ID = "text-data-cleaning-v1"
PROCESSING_HEADERS = ["source_row", "status", "result", "error_code"]


@dataclass
class Table:
    """선택 시트의 원본 값·파일 해시·원본 행 번호를 담는다."""

    headers: list[str]
    rows: list[list]
    digest: str
    sheet: str
    source_rows: list[int]


@dataclass
class Checkpoint:
    """한 시점에 읽은 데이터·처리 상태·실행 정보를 함께 보관한다."""

    headers: list[str]
    rows: list[list]
    processing: list[list]
    metadata: dict
    digest: str


def valid_excel_text(value: str) -> bool:
    """문자열이 절단이나 XML 손상 없이 Excel 셀에 들어갈 수 있는지 확인한다."""
    try:
        units = len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError:
        return False
    return units <= 32767 and re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]", value) is None


def blank(value: object) -> bool:
    """결측 셀과 공백뿐인 문자열을 빈 본문으로 판별한다."""
    return value is None or isinstance(value, str) and not value.strip()


def validate_grid(headers: list, rows: list[list]) -> None:
    """헤더·행 폭·셀 저장 제약을 모델 호출 전에 확인한다."""
    if (not headers or any(not isinstance(x, str) or not x.strip() for x in headers)
            or len(set(headers)) != len(headers)):
        raise CleaningError("첫 행에는 비어 있지 않은 고유한 컬럼 이름이 필요합니다.")
    if len(headers) > 16384 or len(rows) > 1048575:
        raise CleaningError("입력이 Excel의 행 또는 열 제한을 초과했습니다.")
    for row in [headers] + rows:
        if len(row) != len(headers):
            raise CleaningError("입력 행의 컬럼 수가 헤더와 다릅니다.")
        for value in row:
            if isinstance(value, str) and not valid_excel_text(value):
                raise CleaningError("Excel에 보존할 수 없는 길이 또는 제어문자가 있습니다. 원문을 자동 절단하지 않습니다.")
            if isinstance(value, float) and not math.isfinite(value):
                raise CleaningError("유한하지 않은 숫자는 Excel에 그대로 저장할 수 없습니다.")


def worksheet_grid(worksheet) -> list[list]:
    """시트의 값을 읽고 캐시가 불확실한 수식을 조용히 결측으로 바꾸지 않는다."""
    rows = []
    for cells in worksheet.iter_rows():
        if any(cell.data_type == "f" for cell in cells):
            raise CleaningError("선택한 시트에 수식이 있습니다. 값으로 확정한 별도 입력을 사용하세요.")
        rows.append([cell.value for cell in cells])
    return rows


def read_metadata(workbook, *, required: bool = False) -> dict | None:
    """이 도구의 실행 시트만 인식하고 일반 입력의 다른 시트는 작업 상태로 간주하지 않는다."""
    if "run" not in workbook.sheetnames:
        if required:
            raise CleaningError("체크포인트 실행 정보가 없습니다.")
        return None
    grid = [list(row) for row in workbook["run"].iter_rows(values_only=True)]
    candidate = (grid and grid[0] == ["key", "value"]
                 and any(len(row) == 2 and row[0] == "format" and isinstance(row[1], str)
                         and "text-data-cleaning-" in row[1] for row in grid[1:]))
    if not candidate:
        if required:
            raise CleaningError("이 도구의 체크포인트 파일이 아닙니다.")
        return None
    try:
        result = {key: json.loads(value) for key, value in grid[1:]}
        if len(result) != len(grid) - 1 or result.get("format") != FORMAT_ID:
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise CleaningError("체크포인트 실행 정보의 형식 또는 버전이 다릅니다.") from None


def read_processing(grid: list[list], row_count: int) -> list[list]:
    """처리 시트의 행 식별자·상태·결과 조합을 검증하고 빈 결과를 복원한다."""
    if not grid or grid[0] != PROCESSING_HEADERS or len(grid) - 1 != row_count:
        raise CleaningError("체크포인트의 처리 시트 또는 행 수가 올바르지 않습니다.")
    result = []
    numbers = set()
    for row in grid[1:]:
        if len(row) != 4:
            raise CleaningError("체크포인트 처리 행의 형식이 다릅니다.")
        number, status, content, error = row
        if type(number) is not int or number < 2 or number in numbers:
            raise CleaningError("체크포인트 원본 행 번호가 올바르지 않습니다.")
        numbers.add(number)
        if status == "completed":
            valid = isinstance(content, str) and bool(content.strip()) and valid_excel_text(content) and error is None
        elif status == "review_required":
            valid = blank(content) and error == "EMPTY_RESULT"
            content = "" if content is None else content
        elif status in ("pending", "skipped"):
            valid = content is None and error is None
        elif status == "error":
            valid = content is None and error in ("API_ERROR", "INVALID_RESULT")
        else:
            valid = False
        if not valid:
            raise CleaningError("체크포인트의 상태와 결과가 일치하지 않습니다.")
        result.append([number, status, content, error])
    return result


def checkpoint_from_workbook(workbook, digest: str, metadata: dict) -> Checkpoint:
    """실행 시트와 데이터·처리 시트가 서로 일치하는지 검사한다."""
    try:
        grid = worksheet_grid(workbook["data"])
        if not grid:
            raise ValueError
        headers, rows = grid[0], grid[1:]
        validate_grid(headers, rows)
        if type(metadata.get("row_count")) is not int or metadata["row_count"] != len(rows):
            raise ValueError
        column = headers.index(metadata["column"])
        processing = read_processing(worksheet_grid(workbook["processing"]), len(rows))
        for row, record in zip(rows, processing):
            if record[1] in ("completed", "review_required"):
                if (row[column] if row[column] is not None else "") != record[2]:
                    raise ValueError
            elif record[1] == "skipped" and not blank(row[column]):
                raise ValueError
        return Checkpoint(headers, rows, processing, metadata, digest)
    except (KeyError, ValueError, TypeError, IndexError):
        raise CleaningError("체크포인트의 데이터·처리 상태·실행 정보가 일치하지 않습니다.") from None


def load_checkpoint(path: str | Path) -> Checkpoint:
    """체크포인트 파일을 한 번 읽은 스냅샷에서 재개 정보를 추출한다."""
    from openpyxl import load_workbook

    try:
        data = Path(path).read_bytes()
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=False)
    except Exception:
        raise CleaningError("체크포인트 파일을 읽을 수 없습니다.") from None
    try:
        metadata = read_metadata(workbook, required=True)
        return checkpoint_from_workbook(workbook, hashlib.sha256(data).hexdigest(), metadata)
    finally:
        workbook.close()


def read_input(path: str | Path, settings: Settings) -> Table:
    """CSV 문자열 또는 선택한 Excel 시트를 읽으며 미완료 정제 파일의 단계 연결을 막는다."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError:
        raise CleaningError("입력 파일을 읽을 수 없습니다.") from None
    digest = hashlib.sha256(data).hexdigest()
    if path.suffix.lower() == ".csv":
        try:
            grid = list(csv.reader(StringIO(data.decode(settings.encoding), newline=""), strict=True))
        except (UnicodeError, csv.Error):
            raise CleaningError("CSV 형식 또는 인코딩을 확인하세요.") from None
        if not grid:
            raise CleaningError("입력에 헤더가 없습니다.")
        headers = grid[0]
        rows = [row if row else [""] * len(headers) for row in grid[1:]]
        sheet = "CSV"
    elif path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook

        try:
            workbook = load_workbook(BytesIO(data), read_only=True, data_only=False)
        except Exception:
            raise CleaningError("입력 Excel 파일을 읽을 수 없습니다.") from None
        try:
            metadata = read_metadata(workbook)
            if metadata is not None:
                checkpoint = checkpoint_from_workbook(workbook, digest, metadata)
                if settings.sheet not in (0, "data"):
                    raise CleaningError("정제 결과를 연결할 때는 data 시트를 사용하세요.")
                if any(row[1] not in ("completed", "skipped") for row in checkpoint.processing):
                    raise CleaningError("입력 정제 파일에 미완료 또는 검토 필요 행이 있습니다. 먼저 처리·검토를 마치세요.")
                return Table(checkpoint.headers, checkpoint.rows, digest, "data",
                             [row[0] for row in checkpoint.processing])
            worksheet = (workbook.worksheets[settings.sheet] if type(settings.sheet) is int
                         else workbook[settings.sheet])
            grid = worksheet_grid(worksheet)
            if not grid:
                raise CleaningError("선택한 시트에 헤더가 없습니다.")
            headers, rows, sheet = grid[0], grid[1:], worksheet.title
        except (KeyError, IndexError):
            raise CleaningError("지정한 시트를 찾을 수 없습니다.") from None
        finally:
            workbook.close()
    else:
        raise CleaningError("입력 형식은 .csv 또는 .xlsx여야 합니다.")
    validate_grid(headers, rows)
    return Table(headers, rows, digest, sheet, list(range(2, len(rows) + 2)))


def check_new_path(path: str | Path) -> Path:
    """기존 결과와 링크를 덮어쓰지 않도록 새 경로를 확인한다."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise CleaningError("출력 경로가 이미 있습니다. 새 경로 또는 명시적인 --resume을 사용하세요.")
    return path


@contextmanager
def output_lock(path: str | Path):
    """같은 출력의 동시 실행을 막고 정상 종료·예외 시 잠금을 정리한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise CleaningError("같은 출력의 잠금 파일이 있습니다. 실행 중인지 확인하세요.") from None
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def write_workbook(path: str | Path, sheets: dict[str, list[list]], *, replace: bool = False) -> str:
    """완성된 임시 Excel만 확정하고 그 파일 해시를 반환하며 텍스트를 수식으로 바꾸지 않는다."""
    from openpyxl import Workbook

    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        raise CleaningError("결과 파일은 .xlsx 경로여야 합니다.")
    if not replace:
        check_new_path(path)
    for grid in sheets.values():
        if not grid:
            raise CleaningError("출력 시트에 헤더가 필요합니다.")
        validate_grid(grid[0], grid[1:])
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".cleaning-", suffix=".xlsx", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    workbook = Workbook()
    workbook.remove(workbook.active)
    try:
        for title, grid in sheets.items():
            worksheet = workbook.create_sheet(title)
            for row_number, row in enumerate(grid, 1):
                for column_number, value in enumerate(row, 1):
                    cell = worksheet.cell(row_number, column_number, value)
                    if isinstance(value, str):
                        cell.data_type = "s"
        workbook.save(temporary)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
        return digest
    finally:
        workbook.close()
        temporary.unlink(missing_ok=True)
