"""Excel의 원본 값·행 번호를 보존하고 결과를 원자적으로 저장한다."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from io import BytesIO
import os
from pathlib import Path
import tempfile

from config import SurveyError


@dataclass
class Table:
    """헤더와 셀 값, 원본 파일 해시 및 선택한 시트를 보관한다."""

    headers: list[str]
    rows: list[list]
    digest: str
    sheet: str


def read_table(path: str | Path, sheet: str | int = 0) -> Table:
    """xlsx 스냅샷을 읽으며 중복 헤더·수식·잘못된 시트는 명시적으로 거부한다."""
    from openpyxl import load_workbook

    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        raise SurveyError("입력은 .xlsx 파일이어야 합니다.")
    try:
        data = path.read_bytes()
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=False)
    except Exception:
        raise SurveyError("입력 Excel 파일을 읽을 수 없습니다.") from None
    try:
        worksheet = workbook.worksheets[sheet] if type(sheet) is int else workbook[sheet]
        cells = list(worksheet.iter_rows())
        if not cells:
            raise SurveyError("첫 행에 컬럼 이름이 필요합니다.")
        if any(cell.data_type == "f" for row in cells for cell in row):
            raise SurveyError("입력에 Excel 수식이 있습니다. 값으로 확정한 별도 파일을 사용하세요.")
        headers = [cell.value for cell in cells[0]]
        if any(not isinstance(x, str) or not x.strip() for x in headers) or len(set(headers)) != len(headers):
            raise SurveyError("컬럼 이름은 비어 있지 않은 고유한 문자열이어야 합니다.")
        rows = [[cell.value for cell in row] for row in cells[1:]]
        return Table(headers, rows, hashlib.sha256(data).hexdigest(), worksheet.title)
    except (KeyError, IndexError, TypeError):
        raise SurveyError("지정한 시트를 찾을 수 없습니다.") from None
    finally:
        workbook.close()


def source_rows(table: Table) -> list[int]:
    """추출 단계의 원본 행 번호가 있으면 이어 쓰고 없으면 Excel 행 번호를 부여한다."""
    if "source_row" not in table.headers:
        return list(range(2, len(table.rows) + 2))
    column = table.headers.index("source_row")
    values = [row[column] for row in table.rows]
    if any(type(x) is not int or x < 2 for x in values) or len(set(values)) != len(values):
        raise SurveyError("source_row는 중복 없는 2 이상의 원본 행 번호여야 합니다.")
    return values


def check_new_path(path: str | Path) -> Path:
    """기존 결과나 링크를 덮어쓰지 않을 새 출력 경로를 확인한다."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise SurveyError("출력 경로가 이미 있습니다. 새 경로 또는 명시적인 --resume을 사용하세요.")
    return path


@contextmanager
def output_lock(path: str | Path):
    """같은 출력의 동시 실행을 막고 정상 종료·예외 시 잠금 파일을 제거한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise SurveyError("같은 출력의 잠금 파일이 있습니다. 실행 중인지 확인하세요.") from None
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def write_workbook(path: str | Path, sheets: dict[str, list[list]], *, replace: bool = False) -> None:
    """임시 xlsx 작성 후 확정하며 문자열을 수식으로 변환하지 않는다."""
    from openpyxl import Workbook

    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        raise SurveyError("Excel 출력 확장자는 .xlsx여야 합니다.")
    if not replace:
        check_new_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".survey-", suffix=".xlsx", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    workbook = Workbook()
    workbook.remove(workbook.active)
    try:
        for title, rows in sheets.items():
            worksheet = workbook.create_sheet(title)
            for row_number, row in enumerate(rows, 1):
                for column_number, value in enumerate(row, 1):
                    cell = worksheet.cell(row_number, column_number)
                    if isinstance(value, str):
                        if len(value) > 32767:
                            raise SurveyError("Excel 셀 길이 제한을 초과했습니다. 원문을 자동으로 자르지 않습니다.")
                        cell.value = value
                        cell.data_type = "s"
                    else:
                        cell.value = value
        workbook.save(temporary)
        if replace:
            os.replace(temporary, path)
        else:
            # 같은 볼륨의 하드 링크로 기존 경로를 덮어쓰지 않고 완성 파일만 공개한다.
            os.link(temporary, path)
    finally:
        workbook.close()
        temporary.unlink(missing_ok=True)


def extract_columns(input_path: str | Path, output_path: str | Path,
                    columns: list[str], sheet: str | int = 0) -> int:
    """선택한 컬럼과 원본 행 번호를 새 Excel에 저장하며 원본은 변경하지 않는다."""
    check_new_path(output_path)
    table = read_table(input_path, sheet)
    if not columns or len(set(columns)) != len(columns) or any(x not in table.headers for x in columns):
        raise SurveyError("추출 컬럼은 입력에 존재하는 고유한 이름이어야 합니다.")
    selected = [x for x in columns if x != "source_row"]
    indexes = [table.headers.index(x) for x in selected]
    rows = [[number] + [row[i] for i in indexes]
            for number, row in zip(source_rows(table), table.rows)]
    with output_lock(output_path):
        write_workbook(output_path, {"responses": [["source_row"] + selected] + rows})
    return len(rows)
