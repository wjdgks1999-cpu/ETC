"""검토 준비 단계에서 테이블·컬럼 자료의 이름을 대조한다."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import csv

ENGLISH = "테이블영문명"
KOREAN = "테이블한글명"


def clean(value: object) -> str:
    """빈 값은 빈 문자열로 바꾸고 이름의 양끝 공백을 제거한다."""
    return "" if value is None else str(value).strip()


@dataclass
class TableNames:
    """파일별 이름 쌍·고유 이름·누락 행과 비교용 집계를 보관한다."""
    pairs: Counter[tuple[str, str]]
    english: set[str]
    korean: set[str]
    missing: list[tuple[int, str, str]]
    row_count: int
    sheet_name: str


def read_names(path: Path, sheet_name: str | None = None) -> TableNames:
    """헤더의 공백 차이를 허용하고, 이름이 누락된 행은 따로 기록한다."""
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook[sheet_name] if sheet_name else workbook.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        header = next(rows, ())
        positions = {}
        for index, value in enumerate(header):
            name = "".join(clean(value).split())
            if name in (ENGLISH, KOREAN):
                if name in positions:
                    raise ValueError(f"{path.name}: '{name}' 열이 중복됩니다.")
                positions[name] = index
        if not {ENGLISH, KOREAN}.issubset(positions):
            raise ValueError(
                f"{path.name}: 첫 행에 '{ENGLISH}', '{KOREAN}' 열이 필요합니다. "
                f"실제 헤더: {header}"
            )

        result = TableNames(Counter(), set(), set(), [], 0, sheet.title)
        for row_number, row in enumerate(rows, start=2):
            if all(not clean(value) for value in row):
                continue  # 완전히 빈 행만 건너뛴다.
            result.row_count += 1
            english = clean(row[positions[ENGLISH]])
            korean = clean(row[positions[KOREAN]])
            if english:
                result.english.add(english)
            if korean:
                result.korean.add(korean)
            if not english or not korean:
                result.missing.append((row_number, english, korean))
            else:
                result.pairs[(english, korean)] += 1
        return result
    finally:
        workbook.close()


def compare_sets(left: set, right: set) -> dict[str, list]:
    """양쪽 공통 이름과 각 자료에만 있는 이름을 정렬해 반환한다."""
    return {
        "양쪽 모두 존재": sorted(left & right),
        "테이블정보에만 존재": sorted(left - right),
        "컬럼정보에만 존재": sorted(right - left),
    }

def compare_files(tables: Path, columns: Path, *, table_sheet: str | None = None,
                  column_sheet: str | None = None, show_common: bool = False,
                  output: Path | None = None) -> dict:
    """두 자료의 이름·누락을 비교해 출력하며, 요청한 경우 CSV를 저장한다."""
    table_names = read_names(tables, table_sheet)
    column_names = read_names(columns, column_sheet)
    for label, path, source in (
        ("테이블정보", tables, table_names), ("컬럼정보", columns, column_names)
    ):
        print(f"{label}: {path.name} / 시트 {source.sheet_name} / "
              f"데이터 {source.row_count}행 / 고유 이름 쌍 {len(source.pairs)}개")

    comparisons = {
        "영문명·한글명 쌍": compare_sets(set(table_names.pairs), set(column_names.pairs)),
        "영문명": compare_sets(table_names.english, column_names.english),
        "한글명": compare_sets(table_names.korean, column_names.korean),
    }
    print("\n비교 기준: 앞뒤 공백 제거, 대소문자·내부 공백 유지, 중복 제거")
    print("이름이 누락된 행은 쌍 비교에서 제외하고, 개별 이름 비교에는 있는 값만 포함합니다.")
    csv_rows = []
    for basis, groups in comparisons.items():
        print(f"\n[{basis} 비교]")
        for status, values in groups.items():
            print(f"{status}: {len(values)}개")
            for value in values:
                if basis == "영문명·한글명 쌍":
                    english, korean = value
                elif basis == "영문명":
                    english, korean = value, ""
                else:
                    english, korean = "", value
                csv_rows.append((basis, status, english, korean, "", ""))
                if show_common or status != "양쪽 모두 존재":
                    print(f"  {english} | {korean}" if english and korean
                          else f"  {english or korean}")

    print("\n[이름 누락 행]")
    for label, source in (("테이블정보", table_names), ("컬럼정보", column_names)):
        print(f"{label}: {len(source.missing)}행")
        for row_number, english, korean in source.missing:
            print(f"  Excel {row_number}행: {english or '(영문명 없음)'} | "
                  f"{korean or '(한글명 없음)'}")
            csv_rows.append(("이름 누락", label, english, korean,
                             source.sheet_name, row_number))

    if output:
        if output.resolve() in (tables.resolve(), columns.resolve()):
            raise ValueError("출력 경로는 원본 파일과 달라야 합니다.")
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(("비교 기준", "구분", "테이블명(영문명)",
                             "테이블명(한글명)", "시트", "Excel 행"))
            writer.writerows(csv_rows)
        print(f"\n전체 결과 저장: {output.resolve()}")
    return comparisons
