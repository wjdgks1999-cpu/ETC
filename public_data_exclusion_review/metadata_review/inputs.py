"""Excel 메타데이터를 읽고 모델에 전달할 항목만 구성한다."""

from pathlib import Path
import pandas as pd

from .schemas import INPUT_COLUMNS, CONTEXT_COLUMNS, InputError


def clean(value: object) -> str:
    """빈 값은 빈 문자열로 바꾸고 이름의 양끝 공백만 제거한다."""
    return "" if value is None or pd.isna(value) else str(value).strip()


def header_name(value: object) -> str:
    """항목 이름의 공백 차이를 제거해 헤더 비교에 사용한다."""
    return "".join(clean(value).split())


def read_sheet(path: Path, required: list[str], sheet_name: str | None = None) -> pd.DataFrame:
    """필수 헤더의 공백 차이를 허용하며 중복·누락을 검사해 표준 이름으로 읽는다."""
    path = Path(path)
    with pd.ExcelFile(path, engine="openpyxl") as workbook:
        sheet = sheet_name if sheet_name is not None else workbook.sheet_names[0]
        raw_header = pd.read_excel(workbook, sheet_name=sheet, header=None, nrows=1)
        if raw_header.empty:
            raise InputError(f"{path.name}: 머리글이 없습니다.")
        keys = [header_name(value) for value in raw_header.iloc[0]]
        rename = {}
        for name in required:
            positions = [i for i, key in enumerate(keys) if key == header_name(name)]
            if not positions:
                raise InputError(f"{path.name}: 필요한 항목이 없습니다: {name}")
            if len(positions) > 1:
                raise InputError(f"{path.name}: 항목이 중복됩니다: {name}")
            rename[positions[0]] = name
        frame = pd.read_excel(workbook, sheet_name=sheet)
    frame.columns = [rename.get(i, name) for i, name in enumerate(frame.columns)]
    return frame


def load_inputs(tables_path: Path, columns_path: Path, *, limit: int | None = None,
                table_sheet: str | None = None, column_sheet: str | None = None) -> tuple[pd.DataFrame, list[dict]]:
    """영문 테이블명으로 자료를 연결하고 허용된 컬럼 정보와 보조 맥락만 반환한다."""
    if limit is not None and limit < 1:
        raise InputError("처리 한도는 1 이상이어야 합니다.")
    required = ["테이블한글명", "테이블영문명", *CONTEXT_COLUMNS.values()]
    table_df = read_sheet(tables_path, required, table_sheet)
    columns_df = read_sheet(columns_path, INPUT_COLUMNS, column_sheet)[INPUT_COLUMNS].copy()
    table_ids = table_df["테이블영문명"].map(clean)
    if table_df["테이블한글명"].map(clean).eq("").any():
        raise InputError("테이블 목록에 빈 테이블명이 있습니다.")
    if table_ids.eq("").any():
        raise InputError("테이블 목록에 빈 테이블 영문명이 있습니다.")
    if table_ids.duplicated().any():
        raise InputError("테이블 영문명이 중복되어 있습니다.")
    if limit is not None:
        table_df = table_df.head(limit).copy()
    table_df = table_df.reset_index(drop=True)
    column_ids = columns_df["테이블 영문명"].map(clean)
    prepared = []
    for _, table in table_df.iterrows():
        table_name, table_id = table["테이블한글명"], clean(table["테이블영문명"])
        selected = columns_df[column_ids == table_id]
        if selected.empty:
            raise InputError(f"컬럼 정보가 없는 테이블: {table_name} ({table_id})")
        prepared.append({
            "table_name": table_name,
            "columns_df": selected.to_json(orient="records", force_ascii=False),
            **{key: clean(table[column]) for key, column in CONTEXT_COLUMNS.items()},
        })
    return table_df, prepared
