"""Excel 입출력과 계산에 필요한 데이터 검증을 담당한다."""

import json
import os
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from config import WorkflowError


def validate_table(data):
    """빈 입력과 중복·비문자 컬럼명을 거부하고 행 인덱스를 정규화한다."""
    if data.empty or data.columns.empty:
        raise WorkflowError("평가·생성할 데이터가 비어 있습니다.")
    if (not data.columns.is_unique or
            any(not isinstance(c, str) or not c.strip() for c in data.columns)):
        raise WorkflowError("컬럼명은 비어 있지 않은 고유 문자열이어야 합니다.")
    return data.reset_index(drop=True).copy()


def read_table(path):
    """첫 시트를 읽으며 pandas가 바꾸기 전의 중복 Excel 헤더도 검사한다."""
    try:
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            sheet = book.worksheets[0]
            header = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
            if (not header or any(not isinstance(c, str) or not c.strip() for c in header)
                    or len(set(header)) != len(header)):
                raise WorkflowError("Excel 첫 행에 고유한 컬럼명을 지정하세요.")
        finally:
            book.close()
        return validate_table(pd.read_excel(path, engine="openpyxl"))
    except WorkflowError:
        raise
    except Exception as error:
        raise WorkflowError("입력 Excel을 읽을 수 없습니다. 경로와 파일 형식을 확인하세요.") from error


def resolve_types(data, overrides):
    """원본에서 평가 유형을 한 번 정하고 명시적 컬럼 설정을 적용한다."""
    if set(overrides) - set(data.columns):
        raise WorkflowError("column_types에 입력에 없는 컬럼이 있습니다.")
    return {
        col: overrides.get(col, "numerical" if pd.api.types.is_numeric_dtype(data[col])
                           and not pd.api.types.is_bool_dtype(data[col]) else "categorical")
        for col in data.columns
    }


def check_types(data, types):
    """수치형 컬럼의 문자 혼입과 무한대를 원본 값을 출력하지 않고 거부한다."""
    for col, kind in types.items():
        values = data[col].dropna()
        if kind == "numerical" and len(values):
            if (not pd.api.types.is_numeric_dtype(values) or
                    pd.api.types.is_bool_dtype(values)):
                raise WorkflowError("수치형으로 지정한 컬럼에 비수치 값이 있습니다.")
            if not np.isfinite(values.to_numpy(dtype=float)).all():
                raise WorkflowError("수치형 컬럼에 무한대가 있습니다.")


def align_tables(origin, synthetic, types):
    """동일한 컬럼 집합을 확인하고 원본 순서로 정렬하여 유형을 검사한다."""
    origin, synthetic = validate_table(origin), validate_table(synthetic)
    if set(origin.columns) != set(synthetic.columns) or set(types) != set(origin.columns):
        raise WorkflowError("원본·합성·평가 설정의 컬럼 집합이 일치하지 않습니다.")
    synthetic = synthetic.loc[:, origin.columns]
    check_types(origin, types)
    check_types(synthetic, types)
    return origin, synthetic


def check_output(path, overwrite=False):
    """계산 전에 출력 파일의 덮어쓰기 조건을 검사한다."""
    path = Path(path)
    if path.exists() and (not overwrite or not path.is_file()):
        raise WorkflowError("출력 경로가 이미 존재합니다. 파일 교체에는 --overwrite가 필요합니다.")


def metadata_sheet(values):
    """구조화된 실행 정보를 Excel의 키·JSON 값 시트로 변환한다."""
    return pd.DataFrame([
        {"key": key, "value": json.dumps(value, ensure_ascii=False, allow_nan=False)}
        for key, value in values.items()
    ])


def read_metadata(frame):
    """메타데이터 시트를 읽고 누락·중복 키와 잘못된 JSON을 거부한다."""
    if set(frame.columns) != {"key", "value"} or frame["key"].duplicated().any():
        raise WorkflowError("실행 정보 시트의 형식이 올바르지 않습니다.")
    try:
        return {row.key: json.loads(row.value) for row in frame.itertuples(index=False)}
    except (TypeError, ValueError) as error:
        raise WorkflowError("실행 정보의 JSON 값을 읽을 수 없습니다.") from error


def write_workbook(path, sheets, overwrite=False):
    """임시 Excel을 완성한 뒤 게시하여 실패 시 기존 결과를 보존한다."""
    path = Path(path)
    check_output(path, overwrite)
    if not sheets:
        raise WorkflowError("저장할 결과 시트가 없습니다.")
    for frame in sheets.values():
        if len(frame) > 1048575 or len(frame.columns) > 16384:
            raise WorkflowError("Excel의 행 또는 열 수 한도를 초과합니다.")
        if any(isinstance(value, str) and len(value) > 32767
               for row in frame.itertuples(index=False, name=None) for value in row):
            raise WorkflowError("Excel 셀의 최대 문자열 길이를 초과합니다.")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=".synthetic-", suffix=".xlsx", dir=path.parent)
    os.close(handle)
    temporary = Path(name)
    try:
        # ExcelWriter의 종료 처리에서 오류가 나도 외부 파일 핸들은 닫는다.
        with temporary.open("wb") as stream:
            with pd.ExcelWriter(stream, engine="openpyxl") as writer:
                try:
                    for sheet_name, frame in sheets.items():
                        frame.to_excel(writer, sheet_name=sheet_name, index=False)
                    # 데이터 문자열을 Excel 수식으로 실행하지 않는다.
                    for sheet in writer.book.worksheets:
                        for row in sheet:
                            for cell in row:
                                if cell.data_type == "f":
                                    cell.data_type = "s"
                except Exception:
                    # 빈 통합문서의 종료 오류가 최초 저장 오류를 가리지 않게 한다.
                    if not writer.book.worksheets:
                        writer.book.create_sheet("incomplete")
                    raise
        if overwrite:
            os.replace(temporary, path)
        else:
            # 같은 디렉터리의 하드링크 생성은 기존 파일을 원자적으로 보호한다.
            os.link(temporary, path)
    except FileExistsError as error:
        raise WorkflowError("저장 중 출력 파일이 생겼습니다. 기존 파일은 보존했습니다.") from error
    finally:
        temporary.unlink(missing_ok=True)
