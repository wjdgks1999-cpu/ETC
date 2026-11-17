"""비공개 원본과 API 호출 없이 사용할 가상 메타데이터를 만든다."""

import json
import os
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from metadata_review.schemas import ExclusionResult


def make_result(name="API KEY 관리", reason="API 비밀번호명 등 API 설정을 관리하는 데이터이므로 개방에서 제외"):
    """작성·교정 단계의 대체 응답으로 사용할 검토 결과를 만든다."""
    return ExclusionResult(table_name=name, exclusion_code="9", exclusion_reason=reason,
                           review_required=False, review_comment="API 설정 관리 목적을 근거로 판단함")


def make_source(overrides=None, *, count=3):
    """모델 처리 검증에 쓸 컬럼 정보와 보조 맥락을 구성한다."""
    source = {"table_name": "API KEY 관리", "information_system_name": "예제 시스템",
              "logical_db_name": "예제 DB"}
    source.update(overrides or {})
    if not json.loads(source.get("columns_df", "[]")):
        source["columns_df"] = json.dumps([
            {"테이블 한글명": source["table_name"], "테이블 영문명": "settings",
             "컬럼명(한글)": name, "컬럼명(영문)": f"field_{index}", "데이터타입": "VARCHAR"}
            for index, name in enumerate(["API 비밀번호명", "설정명", "사용여부"][:count])
        ], ensure_ascii=False)
    return source


def write_inputs(directory: Path, counts=(3,), names=None):
    """원하는 컬럼 수의 가상 테이블·컬럼 Excel 두 파일을 생성한다."""
    tables, columns = [], []
    for index, count in enumerate(counts):
        name = names[index] if names else f"예제 테이블 {index}"
        table_id = f"table_{index}"
        tables.append({"테이블한글명": name, "테이블영문명": table_id,
                       "정보시스템명": "예제 시스템", "논리DB명": "예제 DB"})
        for number in range(count):
            columns.append({"테이블 한글명": name, "테이블 영문명": table_id,
                            "컬럼명(한글)": f"설정항목 {number}", "컬럼명(영문)": f"field_{number}",
                            "데이터타입": "VARCHAR", "PK여부": "예시", "공개구분": "예시", "비공개사유": "예시"})
    table_path, column_path = directory / "tables.xlsx", directory / "columns.xlsx"
    pd.DataFrame(tables).to_excel(table_path, index=False)
    pd.DataFrame(columns).to_excel(column_path, index=False)
    return table_path, column_path
