"""수집 결과를 정해진 열 구조로 저장하고 진행 상태·오류를 별도로 기록한다."""

import json
import os
from pathlib import Path
import tempfile

import pandas as pd

from .common import CrawlConfig, CrawlResult

USECASE_COLUMNS = ["페이지", "페이지내순번", "활용사례일련번호", "서비스명", "개발유형",
                   "서비스설명", "서비스URL", "등록일", "활용데이터수", "활용데이터목록",
                   "상세페이지URL", "수집오류"]
DATA_COLUMNS = ["서비스명", "활용사례일련번호", "순번", "데이터유형", "데이터명", "상세페이지URL"]


def output_paths(config: CrawlConfig) -> list[Path]:
    """수집 대상에 따라 생성할 Excel·상태 파일과 선택적인 CSV 경로를 반환한다."""
    paths = [config.output, config.output.with_suffix(".status.json")]
    if config.target == "usecase":
        paths.append(config.output.with_suffix(".csv"))
    return paths


def check_output(config: CrawlConfig):
    """교체 허용 없이 같은 이름의 출력 파일이 존재하면 실행을 중단한다."""
    existing = [str(p) for p in output_paths(config) if p.exists()]
    if existing and not config.overwrite:
        raise FileExistsError("기존 출력이 있습니다. 다른 --output 또는 --overwrite를 사용하세요: " + ", ".join(existing))


def atomic_write(path: Path, write):
    """콜백으로 임시 파일을 완성한 뒤 대상 파일을 교체하고, 실패 시 임시 파일을 정리한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".crawl-", suffix=path.suffix, dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        write(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save(config: CrawlConfig, result: CrawlResult):
    """대상별 Excel과 진행 상태를 저장한다. 활용사례는 연결 데이터 시트와 CSV도 작성한다."""
    if config.target == "file":
        columns = ["데이터명", "제공기관명"]
    elif config.target == "api":
        columns = ["기관명", "유형", "데이터명", "조회수", "활용신청건수"]
    else:
        columns = USECASE_COLUMNS

    main = pd.DataFrame(result.rows).reindex(columns=columns)
    data_rows = []
    for row in result.rows:
        for order, item in enumerate(row.get("_data", []), 1):
            data_rows.append({"서비스명": row.get("서비스명", ""),
                              "활용사례일련번호": row.get("활용사례일련번호", ""),
                              "순번": order, **item, "상세페이지URL": row.get("상세페이지URL", "")})

    def write_excel(path):
        """결과 시트를 작성하고, 수집 문자열이 Excel 수식으로 해석되지 않도록 처리한다."""
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            main.to_excel(writer, sheet_name="활용사례" if config.target == "usecase" else "Sheet1", index=False)
            if config.target == "usecase":
                pd.DataFrame(data_rows, columns=DATA_COLUMNS).to_excel(writer, sheet_name="활용데이터", index=False)
            # '='로 시작하는 수집 내용도 수식이 아닌 문자열로 저장한다.
            for sheet in writer.book.worksheets:
                for cells in sheet.iter_rows():
                    for cell in cells:
                        if cell.data_type == "f":
                            cell.data_type = "s"

    # 첫 페이지 수집 실패로 기존 파일을 빈 결과로 덮어쓰지 않는다.
    if result.rows or not result.errors:
        atomic_write(config.output, write_excel)
        if config.target == "usecase":
            atomic_write(config.output.with_suffix(".csv"), lambda p: main.to_csv(p, index=False, encoding="utf-8-sig"))
    status = {"target": config.target, "source_url": config.url, "pages": result.pages,
              "succeeded": result.succeeded, "failed": result.failed,
              "stopped": result.stopped, "errors": result.errors}
    atomic_write(config.output.with_suffix(".status.json"),
                 lambda p: p.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"))
