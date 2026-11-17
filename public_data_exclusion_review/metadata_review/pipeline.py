"""테이블별 작성·검수·교정 흐름과 미처리·실패 상태를 관리한다."""

import json
from .schemas import CONTEXT_COLUMNS, ExclusionResult
from .rules import MAX_CORRECTIONS, fixed_result, normalize_result, validate_final

def empty_record(table_name: str) -> dict:
    """미처리 상태의 결과를 만든다. 작성·교정 도중 실패해도 최종 결과는 비워 둔다."""
    return {
        "table_name": table_name,
        "status": "not_processed",
        "draft": None,
        "corrected": None,
        "final": None,
        "review_issues": [],
        "unresolved_issues": [],
        "correction_count": 0,
        "error": "",
    }


async def process_table(inputs: dict, writer, reviewer, corrector) -> dict:
    """컬럼 2개 이하는 고정 규칙을 적용하고, 나머지는 작성·검수·교정·재검수한다."""
    table_name = inputs["table_name"]
    # 세 단계에 같은 주요 입력과 보조 자료를 전달하며, 그 외 메타데이터는 제외한다.
    record = empty_record(table_name)
    record["status"] = "failed"
    stage = "규칙 적용"
    try:
        source = {key: inputs[key] for key in ("table_name", "columns_df", *CONTEXT_COLUMNS)}
        column_count = len(json.loads(source["columns_df"]))
        candidate = fixed_result(table_name, column_count)
        if candidate is not None:
            # 사용자 지정 규칙은 LLM 판단과 일반 사유 문장 형식보다 우선한다.
            record.update(status="completed", final=candidate.model_dump())
            print(f"[규칙 적용] {table_name}: 컬럼 {column_count}개 / 제외코드 9", flush=True)
            return record

        stage = "작성"
        print(f"[작성 시작] {table_name}", flush=True)
        candidate = await writer.ainvoke(source)
        record["draft"] = candidate.model_dump()

        for attempt in range(MAX_CORRECTIONS + 1):
            # 형식만 정리한 결과를 검수하므로 문장 형식 때문에 교정 호출을 반복하지 않는다.
            candidate = normalize_result(candidate, source["columns_df"])
            if attempt:
                record["corrected"] = candidate.model_dump()
            stage = "검수"
            print(f"[검수 {attempt + 1}차] {table_name}", flush=True)
            review_input = {**source, "result_json": candidate.model_dump_json()}
            review = await reviewer.ainvoke(review_input)
            issues = list(review.issues)
            # 의미 검수와 함께 금지 표현·필드 일관성 오류를 확인한다.
            try:
                validate_final(candidate, table_name)
            except ValueError as error:
                issues.append(str(error))
            record["unresolved_issues"] = issues
            if not issues:
                # 코드 없음은 자동 개방이 아니라 담당자가 확인할 판단 보류로 남긴다.
                status = "completed" if candidate.exclusion_code is not None else "needs_review"
                record.update(status=status, final=candidate.model_dump())
                return record

            record["review_issues"].extend(issues)
            if attempt == MAX_CORRECTIONS:
                record["status"] = "needs_review"
                return record

            stage = "교정"
            print(f"[교정 {attempt + 1}차] {table_name}", flush=True)
            candidate = await corrector.ainvoke({
                **review_input, "issues_json": json.dumps(issues, ensure_ascii=False),
            })
            record["corrected"] = candidate.model_dump()
            record["correction_count"] += 1
    except Exception as error:
        # SDK 예외 원문은 키/요청 내용을 포함할 수 있어 출력하거나 저장하지 않는다.
        record["error"] = f"{stage} 실패 ({type(error).__name__})"
    return record
