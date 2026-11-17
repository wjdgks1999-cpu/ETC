"""대체 모델 응답으로 작성·검수·교정과 실패 상태 보존을 검증한다."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import pandas as pd
from langchain_core.runnables import RunnableLambda
from helpers import make_result as result, make_source
from metadata_review import pipeline, export
from metadata_review.schemas import ReviewResult
from metadata_review.rules import MAX_CORRECTIONS

class PipelineTests(unittest.IsolatedAsyncioTestCase):

    """테이블별 검토 흐름이 판단 기준과 결과 확정 조건을 지키는지 확인한다."""
    async def test_uncertain_reason_is_corrected_even_when_model_review_passes(self):
        """모델 검수가 통과해도 규칙 위반 사유는 교정되는지 확인한다."""
        issues = []

        async def correct(inputs):
            """교정 단계에 전달된 입력을 기록하고 검증용 결과를 반환한다."""
            issues.extend(json.loads(inputs['issues_json']))
            return result()
        with contextlib.redirect_stdout(io.StringIO()):
            record = await pipeline.process_table(make_source({'table_name': 'API KEY 관리', 'columns_df': '[]'}), RunnableLambda(lambda _: result(reason='실제 내용 확인 전 개방 제외')), RunnableLambda(lambda _: ReviewResult(issues=[])), RunnableLambda(correct))
        self.assertEqual(record['status'], 'completed')
        self.assertEqual(record['correction_count'], 1)
        self.assertTrue(any(('추측' in issue for issue in issues)))
        self.assertNotIn('확인', record['final']['exclusion_reason'])

    async def test_null_result_is_held_and_never_becomes_open_decision(self):
        """코드 없는 결과가 개방 결정으로 바뀌지 않고 판단 보류로 저장되는지 확인한다."""
        candidate = result().model_copy(update={'exclusion_code': None, 'exclusion_reason': '', 'review_required': True, 'review_comment': '전체 관리 목적과 개인정보 구성을 검토했으나 근거가 부족하여 판단 보류'})
        with contextlib.redirect_stdout(io.StringIO()):
            record = await pipeline.process_table(make_source({'table_name': 'API KEY 관리', 'columns_df': '[]'}), RunnableLambda(lambda _: candidate), RunnableLambda(lambda _: ReviewResult(issues=[])), RunnableLambda(lambda _: candidate))
        self.assertEqual(record['status'], 'needs_review')
        self.assertIsNone(record['final']['exclusion_code'])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'result.xlsx'
            export.save_excel(pd.DataFrame({'테이블한글명': [candidate.table_name]}), [record], path)
            saved = pd.read_excel(path)
            self.assertEqual(saved.loc[0, '검토결론'], '판단 보류')

    async def test_review_issues_trigger_correction_and_reinspection(self):
        """검수 지적에 따라 교정·재검수가 실행되고 필요한 입력만 전달되는지 확인한다."""
        received = {}

        async def write(inputs):
            """작성 단계에 전달된 입력을 기록하고 교정이 필요한 초안을 반환한다."""
            received['write'] = inputs
            return result(reason='근거 없는 초안')

        async def review(inputs):
            """검수에 전달된 결과를 기록하고 검증 상황에 맞는 지적 사항을 반환한다."""
            received.setdefault('reviews', []).append(inputs)
            issues = ['초안의 근거 및 종결 표현 수정'] if len(received['reviews']) == 1 else []
            return ReviewResult(issues=issues)

        async def correct(inputs):
            """교정 단계에 전달된 입력을 기록하고 검증용 결과를 반환한다."""
            received['correct'] = inputs
            return result()
        inputs = make_source({'table_name': 'API KEY 관리', 'columns_df': '[]', '공개구분': 'N'})
        with contextlib.redirect_stdout(io.StringIO()):
            record = await pipeline.process_table(inputs, RunnableLambda(write), RunnableLambda(review), RunnableLambda(correct))
        self.assertEqual(record['status'], 'completed')
        self.assertNotEqual(record['draft'], record['final'])
        self.assertEqual(set(received['write']), {'table_name', 'columns_df', 'information_system_name', 'logical_db_name'})
        self.assertEqual(record['correction_count'], 1)
        self.assertEqual(len(received['reviews']), 2)
        self.assertEqual(record['unresolved_issues'], [])
        for inputs in [*received['reviews'], received['correct']]:
            self.assertNotIn('공개구분', inputs)
        self.assertEqual(json.loads(received['reviews'][0]['result_json']), record['draft'])
        self.assertEqual(json.loads(received['reviews'][1]['result_json']), record['final'])
        self.assertIn('초안의 근거 및 종결 표현 수정', received['correct']['issues_json'])

    async def test_format_is_cleaned_before_review_without_model_correction(self):
        """단순 문장 형식은 모델 교정 호출 없이 검수 전에 정리되는지 확인한다."""
        reviewed = []

        async def review(inputs):
            """검수에 전달된 결과를 기록하고 검증 상황에 맞는 지적 사항을 반환한다."""
            reviewed.append(json.loads(inputs['result_json']))
            return ReviewResult(issues=[])

        async def unexpected(_):
            """호출하면 안 되는 교정 단계가 실행될 경우 검증을 실패시킨다."""
            raise AssertionError('단순 형식 정리는 모델 교정이 필요하지 않음')
        reason = '  API 설정·사용 여부를\n 관리하는 시스템 운영정보이므로 개방에서 제외.  '
        with contextlib.redirect_stdout(io.StringIO()):
            record = await pipeline.process_table(make_source({'table_name': 'API KEY 관리', 'columns_df': '[]'}), RunnableLambda(lambda _: result(reason=reason)), RunnableLambda(review), RunnableLambda(unexpected))
        self.assertEqual(record['status'], 'completed')
        self.assertEqual(record['correction_count'], 0)
        self.assertEqual(record['draft']['exclusion_reason'], reason)
        self.assertEqual(record['final']['exclusion_reason'], 'API 설정, 사용 여부를 관리하는 시스템 운영정보이므로 개방에서 제외')
        self.assertEqual(reviewed, [record['final']])

    async def test_corrected_reason_is_cleaned_before_reinspection(self):
        """교정 결과도 형식을 정리한 뒤 재검수하는지 확인한다."""
        reviewed = []

        async def review(inputs):
            """검수에 전달된 결과를 기록하고 검증 상황에 맞는 지적 사항을 반환한다."""
            reviewed.append(json.loads(inputs['result_json']))
            return ReviewResult(issues=[])
        with contextlib.redirect_stdout(io.StringIO()):
            record = await pipeline.process_table(make_source({'table_name': 'API KEY 관리', 'columns_df': '[]'}), RunnableLambda(lambda _: result(reason='내용 확인 전 개방 제외')), RunnableLambda(review), RunnableLambda(lambda _: result(reason=' API 설정·상태를\n관리하는 데이터이므로 제외. ')))
        self.assertEqual(record['status'], 'completed')
        self.assertEqual(record['correction_count'], 1)
        self.assertEqual(record['corrected'], record['final'])
        self.assertEqual(record['final']['exclusion_reason'], 'API 설정, 상태를 관리하는 데이터이므로 제외')
        self.assertEqual(reviewed[-1], record['final'])

    async def test_clean_result_skips_correction(self):

        """문제가 없는 결과는 교정 단계 없이 확정되는지 확인한다."""
        async def unexpected(_):
            """호출하면 안 되는 교정 단계가 실행될 경우 검증을 실패시킨다."""
            raise AssertionError('문제가 없으면 교정을 호출하면 안 됨')
        with contextlib.redirect_stdout(io.StringIO()):
            record = await pipeline.process_table(make_source({'table_name': 'API KEY 관리', 'columns_df': '[]'}), RunnableLambda(lambda _: result()), RunnableLambda(lambda _: ReviewResult(issues=[])), RunnableLambda(unexpected))
        self.assertEqual(record['status'], 'completed')
        self.assertEqual(record['correction_count'], 0)

    async def test_valid_manual_review_flag_is_not_a_processing_error(self):
        """유효한 추가 검토 표시를 처리 오류로 취급하지 않는지 확인한다."""
        candidate = result().model_copy(update={'review_required': True})
        with contextlib.redirect_stdout(io.StringIO()):
            record = await pipeline.process_table(make_source({'table_name': 'API KEY 관리', 'columns_df': '[]'}), RunnableLambda(lambda _: candidate), RunnableLambda(lambda _: ReviewResult(issues=[])), RunnableLambda(lambda _: candidate))
        self.assertEqual(record['status'], 'completed')
        self.assertTrue(record['final']['review_required'])
        self.assertEqual(record['correction_count'], 0)

    async def test_unresolved_issues_do_not_become_final_results(self):
        """최대 교정 후 남은 문제를 최종 결과로 확정하지 않는지 확인한다."""
        with contextlib.redirect_stdout(io.StringIO()):
            record = await pipeline.process_table(make_source({'table_name': 'API KEY 관리', 'columns_df': '[]'}), RunnableLambda(lambda _: result()), RunnableLambda(lambda _: ReviewResult(issues=['근거 확인 필요'])), RunnableLambda(lambda _: result()))
        self.assertEqual(record['status'], 'needs_review')
        self.assertEqual(record['correction_count'], MAX_CORRECTIONS)
        self.assertEqual(record['unresolved_issues'], ['근거 확인 필요'])
        self.assertIsNone(record['final'])

    async def test_failed_correction_is_recorded_without_promoting_draft(self):

        """교정 실패 시 초안을 최종 결과로 쓰지 않고 예외 원문을 노출하지 않는지 확인한다."""
        async def fail(_):
            """민감한 문구를 포함한 예외로 실패 시 정보 노출 여부를 검증한다."""
            raise RuntimeError('sensitive-error-marker')
        with contextlib.redirect_stdout(io.StringIO()):
            record = await pipeline.process_table(make_source({'table_name': 'API KEY 관리', 'columns_df': '[]'}), RunnableLambda(lambda _: result()), RunnableLambda(lambda _: ReviewResult(issues=['사유 수정 필요'])), RunnableLambda(fail))
        self.assertEqual(record['status'], 'failed')
        self.assertTrue(record['error'].startswith('교정 실패'))
        self.assertIsNone(record['final'])
        self.assertNotIn('sensitive-error-marker', json.dumps(record))

    async def test_failed_review_never_promotes_draft_or_discloses_error_text(self):

        """검수 실패 시 초안을 보존하되 최종 결과와 민감한 예외 원문은 남기지 않는지 확인한다."""
        async def fail(_):
            """민감한 문구를 포함한 예외로 실패 시 정보 노출 여부를 검증한다."""
            raise RuntimeError('sensitive-error-marker')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            record = await pipeline.process_table(make_source({'table_name': 'API KEY 관리', 'columns_df': '[]'}), RunnableLambda(lambda _: result()), RunnableLambda(fail), RunnableLambda(lambda _: result()))
        self.assertEqual(record['status'], 'failed')
        self.assertIsNotNone(record['draft'])
        self.assertIsNone(record['final'])
        self.assertNotIn('sensitive-error-marker', output.getvalue() + json.dumps(record))
