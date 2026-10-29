"""테이블정보.xlsx와 컬럼정보.xlsx의 테이블명을 비교한다.

설치: python -m pip install openpyxl
실행: python compare.py
공통 목록 표시: python compare.py --show-common
CSV 저장: python compare.py --output outputs/table_comparison.csv

이름 앞뒤 공백만 제거하며, 대소문자와 이름 내부 공백은 그대로 비교한다.
컬럼정보의 반복 행은 중복을 제거한다. 기본적으로 각 파일의 첫 시트를 읽는다.
원본 Excel 파일은 수정하지 않는다.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import dataclass
from pathlib import Path
import sys


BASE_DIR = Path(__file__).resolve().parent
ENGLISH = "테이블영문명"
KOREAN = "테이블한글명"


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


@dataclass
class TableNames:
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
    return {
        "양쪽 모두 존재": sorted(left & right),
        "테이블정보에만 존재": sorted(left - right),
        "컬럼정보에만 존재": sorted(right - left),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tables", type=Path, default=BASE_DIR / "테이블정보.xlsx")
    parser.add_argument("--columns", type=Path, default=BASE_DIR / "컬럼정보.xlsx")
    parser.add_argument("--table-sheet", help="테이블정보의 시트 이름")
    parser.add_argument("--column-sheet", help="컬럼정보의 시트 이름")
    parser.add_argument("--show-common", action="store_true", help="공통 값도 모두 출력")
    parser.add_argument("--output", type=Path, help="전체 비교 결과를 UTF-8 BOM CSV로 저장")
    args = parser.parse_args()

    try:
        tables = read_names(args.tables, args.table_sheet)
        columns = read_names(args.columns, args.column_sheet)
        for label, path, source in (
            ("테이블정보", args.tables, tables), ("컬럼정보", args.columns, columns)
        ):
            print(f"{label}: {path.name} / 시트 {source.sheet_name} / "
                  f"데이터 {source.row_count}행 / 고유 이름 쌍 {len(source.pairs)}개")

        comparisons = {
            "영문명·한글명 쌍": compare_sets(set(tables.pairs), set(columns.pairs)),
            "영문명": compare_sets(tables.english, columns.english),
            "한글명": compare_sets(tables.korean, columns.korean),
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
                    if args.show_common or status != "양쪽 모두 존재":
                        print(f"  {english} | {korean}" if english and korean
                              else f"  {english or korean}")

        print("\n[이름 누락 행]")
        for label, source in (("테이블정보", tables), ("컬럼정보", columns)):
            print(f"{label}: {len(source.missing)}행")
            for row_number, english, korean in source.missing:
                print(f"  Excel {row_number}행: {english or '(영문명 없음)'} | "
                      f"{korean or '(한글명 없음)'}")
                csv_rows.append(("이름 누락", label, english, korean,
                                 source.sheet_name, row_number))

        if args.output:
            if args.output.resolve() in (args.tables.resolve(), args.columns.resolve()):
                raise ValueError("출력 경로는 원본 파일과 달라야 합니다.")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(("비교 기준", "구분", "테이블명(영문명)",
                                 "테이블명(한글명)", "시트", "Excel 행"))
                writer.writerows(csv_rows)
            print(f"\n전체 결과 저장: {args.output.resolve()}")
        return 0
    except ImportError:
        print("오류: openpyxl이 필요합니다. python -m pip install openpyxl", file=sys.stderr)
    except (OSError, ValueError, KeyError) as error:
        print(f"오류: {error}", file=sys.stderr)
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
