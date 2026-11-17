"""테이블별 작업을 제한된 수로 병렬 실행하고 완료·중단 결과를 보존한다."""

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .config import ReviewConfig
from .export import save_excel
from .inputs import load_inputs
from .pipeline import empty_record, process_table
from .schemas import InputError


@dataclass
class ReviewOutcome:
    """결과 파일과 원래 입력 순서의 처리 기록을 보관한다."""

    output: Path
    records: list[dict]

    @property
    def counts(self) -> Counter:
        """완료·추가 검토·실패·미처리 상태를 구분해 집계한다."""
        return Counter(record["status"] for record in self.records)

    @property
    def exit_code(self) -> int:
        """모든 처리가 완료되면 0, 추가 확인할 항목이 남으면 1을 반환한다."""
        return int(any(record["status"] != "completed" for record in self.records))


def output_path(config: ReviewConfig) -> Path:
    """결과 경로를 정하고 원본 덮어쓰기와 승인하지 않은 파일 교체를 방지한다."""
    path = config.output or config.output_dir / f"제외사유_{datetime.now():%Y%m%d_%H%M%S_%f}.xlsx"
    if path.resolve() in (config.tables.resolve(), config.columns.resolve()):
        raise InputError("출력 경로는 원본 파일과 달라야 합니다.")
    if path.exists() and not config.overwrite:
        raise InputError("출력 파일이 이미 있습니다. 다른 경로나 --overwrite를 지정하세요.")
    return path


async def run_review(config: ReviewConfig) -> ReviewOutcome:
    """입력을 검증하고 테이블을 처리한다. 중단 시에도 완료분과 미처리 상태를 저장한다."""
    table_df, inputs = load_inputs(config.tables, config.columns, limit=config.limit,
                                  table_sheet=config.table_sheet, column_sheet=config.column_sheet)
    if not inputs:
        raise InputError("처리할 테이블이 없습니다.")
    path = output_path(config)
    writer = reviewer = corrector = None
    if any(len(json.loads(item["columns_df"])) > 2 for item in inputs):
        # 고정 규칙으로 처리할 수 없는 테이블이 있을 때만 API 설정과 모델을 준비한다.
        load_dotenv(config.env_file, override=False)
        model_name = config.model or os.environ.get("OPENAI_MODEL")
        if not os.environ.get("OPENAI_API_KEY"):
            raise InputError("OPENAI_API_KEY 설정이 필요합니다.")
        if not model_name:
            raise InputError("--model 또는 OPENAI_MODEL 설정이 필요합니다.")
        from .prompts import build_chains
        writer, reviewer, corrector = build_chains(config.prompt_dir, model_name)

    records = [empty_record(item["table_name"]) for item in inputs]
    semaphore = asyncio.Semaphore(config.max_concurrency)

    async def process_one(index: int, item: dict) -> tuple[int, dict]:
        """동시 실행 수를 제한하고 원래 위치와 함께 테이블 처리 결과를 반환한다."""
        async with semaphore:
            return index, await process_table(item, writer, reviewer, corrector)

    tasks = [asyncio.create_task(process_one(index, item)) for index, item in enumerate(inputs)]
    try:
        for task in asyncio.as_completed(tasks):
            index, record = await task
            records[index] = record
            print(f"[{index + 1}/{len(inputs)}] {record['table_name']}: {record['status']}", flush=True)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # 중단 직전 완료됐지만 아직 전달받지 못한 결과도 보존한다.
        for task in tasks:
            if not task.cancelled() and task.exception() is None:
                index, record = task.result()
                records[index] = record
        save_excel(table_df, records, path)
    return ReviewOutcome(path, records)
