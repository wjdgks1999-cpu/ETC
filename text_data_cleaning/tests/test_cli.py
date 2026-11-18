"""별도 프로세스에서 명령 연결·종료 코드·출력 제한을 확인한다."""

from storage import load_checkpoint
from support import SyntheticCase


class CliTests(SyntheticCase):
    """실제 CLI를 실행하면서 모델 처리만 가상 응답으로 대체한다."""

    def test_help_and_import_have_no_io_or_dependency_side_effects(self):
        """도움말·import가 선택 의존성이나 파일·키 조회를 요구하지 않는지 확인한다."""
        bootstrap = """
import builtins, os, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    '''선택 의존성의 조기 import를 차단한다.'''
    if name.split('.')[0] in {'openpyxl', 'pydantic', 'langchain_core', 'langchain_openai', 'dotenv'}:
        raise RuntimeError('unexpected import')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
before = dict(os.environ)
import config, storage, model, workflow, clean
assert before == dict(os.environ)
raise SystemExit(clean.main(sys.argv[1:]))
"""
        result = self.process(["--help"], bootstrap=bootstrap)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("privacy", result.stdout)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_two_stages_connect_in_separate_processes(self):
        """CSV부터 HTML·개인정보 정제 결과까지 별도 프로세스 명령을 연결한다."""
        source = self.csv_file([["001", "<p>가상 FAKE-PERSON</p>"], ["002", ""]])
        config = self.config_file()
        bootstrap = """
import sys, workflow, clean
def fake_key(path):
    '''실제 키 대신 가상 키를 반환한다.'''
    return 'test-only-key'
def build(settings, key):
    '''정제 방식별 가상 결과를 제공한다.'''
    def clean_text(contents):
        '''가상 태그 또는 가상 개인정보 문구를 제거한다.'''
        if settings.mode == 'html':
            return contents.replace('<p>', '').replace('</p>', '')
        return contents.replace(' FAKE-PERSON', '')
    return clean_text
workflow.read_api_key = fake_key
workflow.build_cleaner = build
raise SystemExit(clean.main(sys.argv[1:]))
"""
        first = self.process(["html", "--input", source, "--output", self.output, "--config", config], bootstrap=bootstrap)
        self.assertEqual(first.returncode, 0, first.stderr)
        second_path = self.directory / "privacy.xlsx"
        second = self.process(["privacy", "--input", self.output, "--output", second_path,
                               "--config", config], bootstrap=bootstrap)
        self.assertEqual(second.returncode, 0, second.stderr)
        result = load_checkpoint(second_path)
        self.assertEqual(result.rows, [["001", "가상"], ["002", None]])
        self.assertEqual([record[0] for record in result.processing], [2, 3])

    def test_failure_resume_and_sensitive_error_text_not_printed(self):
        """오류 종료 1·재개 완료 0과 원격 오류 원문 차단을 확인한다."""
        self.workbook([[1, "first"], [2, "second"]])
        config = self.config_file()
        bootstrap = """
import sys, workflow, clean
def fake_key(path):
    '''실제 키 조회를 대체한다.'''
    return 'test-only-key'
def build(settings, key):
    '''첫 실행의 두 번째 행 실패를 모의한다.'''
    def clean_text(contents):
        '''재개 시에는 미완료 행만 처리한다.'''
        if contents == 'second' and '--resume' not in sys.argv:
            raise RuntimeError('PRIVATE_RESPONSE test-secret')
        if contents == 'first' and '--resume' in sys.argv:
            raise AssertionError('completed row was requested')
        return 'clean-' + contents
    return clean_text
workflow.read_api_key = fake_key
workflow.build_cleaner = build
raise SystemExit(clean.main(sys.argv[1:]))
"""
        arguments = ["html", "--input", self.input, "--output", self.output, "--config", config]
        first = self.process(arguments, bootstrap=bootstrap)
        self.assertEqual(first.returncode, 1, first.stderr)
        self.assertNotIn("PRIVATE_RESPONSE", first.stdout + first.stderr)
        self.assertNotIn("test-secret", first.stdout + first.stderr)
        second = self.process(arguments + ["--resume"], bootstrap=bootstrap)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(load_checkpoint(self.output).rows, [[1, "clean-first"], [2, "clean-second"]])

    def test_review_required_exit_and_next_stage_block(self):
        """빈 결과의 검토 필요 종료 1과 미검토 결과의 다음 단계 거부를 확인한다."""
        self.workbook([[1, "synthetic"]])
        config = self.config_file()
        bootstrap = """
import sys, workflow, clean
def fake_key(path):
    '''가상 키를 반환한다.'''
    return 'test-only-key'
def build(settings, key):
    '''전체 문구가 제거된 가상 결과를 제공한다.'''
    def clean_text(contents):
        '''빈 문자열을 반환한다.'''
        return ''
    return clean_text
workflow.read_api_key = fake_key
workflow.build_cleaner = build
raise SystemExit(clean.main(sys.argv[1:]))
"""
        result = self.process(["privacy", "--input", self.input, "--output", self.output,
                               "--config", config], bootstrap=bootstrap)
        self.assertEqual(result.returncode, 1, result.stderr)
        next_path = self.directory / "next.xlsx"
        result = self.process(["html", "--input", self.output, "--output", next_path, "--config", config])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(next_path.exists())

    def test_all_blank_input_without_api_key(self):
        """빈 입력은 실제 CLI에서도 API 키 없이 처리한다."""
        self.workbook([[1, None], [2, " "]])
        result = self.process(["html", "--input", self.input, "--output", self.output,
                               "--config", self.config_file()])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([record[1] for record in load_checkpoint(self.output).processing], ["skipped", "skipped"])

    def test_missing_key_and_existing_output_exit_two(self):
        """키 누락·기존 출력 보호를 실행 실패 종료 2로 구분한다."""
        self.workbook([[1, "synthetic"]])
        arguments = ["html", "--input", self.input, "--output", self.output, "--config", self.config_file()]
        result = self.process(arguments)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.output.exists())
        self.output.write_bytes(b"preserved")
        result = self.process(arguments)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.output.read_bytes(), b"preserved")
