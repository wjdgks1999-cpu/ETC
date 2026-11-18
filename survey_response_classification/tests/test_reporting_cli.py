"""집계 분모·그래프 출력과 실제 명령의 종료 상태를 검증한다."""

from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import Mock, patch

from config import SurveyError, load_settings
from reporting import aggregate, summarize_file
from storage import Table, read_table
from support import ROOT, SyntheticCase


class ReportingTests(SyntheticCase):
    """복수·단일 집계의 분모와 기타 포함 차이를 검증한다."""

    def test_general_denominator_is_assignments(self):
        """2개 응답의 3개 할당을 응답자 비율로 바꾸지 않고 소수점 1자리로 집계한다."""
        table = Table(["category"], [["홍보, 신규개방"], ["홍보"], [None]], "", "responses")
        summary = aggregate(table, self.settings)
        self.assertEqual(summary.response_count, 2)
        self.assertEqual(summary.denominator, 3)
        self.assertEqual(summary.count_rows(), [["category", "개수", "퍼센트"], ["홍보", 2, 66.7], ["신규개방", 1, 33.3]])
        self.assertEqual(summary.omitted, {"blank_category": 1})

    def test_ai_table_keeps_other_and_unrounded_percentage(self):
        """AI 집계표는 기타를 포함하고 비율을 임의로 반올림하지 않는다."""
        ai = load_settings(ROOT / "config.ai.example.json")
        table = Table(["category"], [[ai.categories[0]], [ai.categories[0]], ["기타"]], "", "responses")
        summary = aggregate(table, ai)
        self.assertEqual(summary.denominator, 3)
        self.assertEqual(summary.count_rows()[1], [ai.categories[0], 2, 2 / 3 * 100])
        self.assertIn(["기타", 1, 1 / 3 * 100], summary.count_rows())
        self.assertIn(["그래프 기타 포함", "제외"], summary.detail_rows())

    def test_incomplete_rows_excluded_and_reported(self):
        """완료되지 않은 행을 분모에서 빼고 각 미집계 상태의 건수를 남긴다."""
        table = Table(["category", "status"], [["홍보", "completed"], [None, "error"],
                      [None, "pending"], [None, "skipped"]], "", "responses")
        summary = aggregate(table, self.settings)
        self.assertEqual(summary.denominator, 1)
        self.assertEqual(summary.omitted, {"error": 1, "pending": 1, "skipped": 1})

    def test_invalid_completed_or_partial_categories_not_silently_dropped(self):
        """잘못된 완료 분류·모순된 미완료 상태·미등록 범주를 집계에서 숨기지 않는다."""
        for rows in ([[None, "completed"]], [["홍보", "error"]], [["홍보", "unknown"]],
                     [["홍보, 홍보", "completed"]], [["없는 범주", "completed"]]):
            with self.subTest(rows=rows), self.assertRaises(SurveyError):
                aggregate(Table(["category", "status"], rows, "", "responses"), self.settings)

    def test_empty_summary_no_division_by_zero(self):
        """유효 분류가 없을 때 빈 집계표와 0 분모를 명시한다."""
        summary = aggregate(Table(["category"], [[None]], "", "responses"), self.settings)
        self.assertEqual(summary.denominator, 0)
        self.assertEqual(len(summary.count_rows()), 1)

    def test_png_and_excel_published_together(self):
        """모의 분류 파일에서 실제 PNG와 분모 시트를 같은 새 폴더에 저장한다."""
        self.workbook([["홍보, 신규개방"], ["홍보"], ["기타"]], headers=["category"])
        output = self.directory / "summary"
        summary = summarize_file(self.input, output, self.settings)
        self.assertEqual(summary.assignment_count, 4)
        self.assertTrue((output / "chart.png").read_bytes().startswith(b"\x89PNG"))
        self.assertIn(["분모 건수", 4], read_table(output / "summary.xlsx", "details").rows)
        before = (output / "chart.png").read_bytes()
        with self.assertRaises(SurveyError):
            summarize_file(self.input, output, self.settings)
        self.assertEqual((output / "chart.png").read_bytes(), before)

    def test_ai_chart_excludes_other_but_table_includes_it(self):
        """실제 그래프 생성 시 기타를 막대에서만 제외하는지 확인한다."""
        from matplotlib import pyplot
        from matplotlib.axes import Axes

        ai = load_settings(ROOT / "config.ai.example.json")
        self.workbook([[ai.categories[0]], ["기타"]], headers=["category"])
        output = self.directory / "summary"
        original = Axes.bar
        plotted = []

        def record(axes, x, height, *args, **kwargs):
            """실제 막대를 그리면서 집계에 전달된 높이를 기록한다."""
            plotted.append(list(height))
            return original(axes, x, height, *args, **kwargs)

        with patch.object(Axes, "bar", new=record):
            summarize_file(self.input, output, ai)
        self.assertEqual(plotted, [[1]])
        self.assertEqual(len(read_table(output / "summary.xlsx", "counts").rows), 2)

    def test_all_other_ai_and_empty_general_charts(self):
        """기타뿐인 AI 결과와 빈 일반 집계도 오류 없이 설명이 있는 PNG로 저장한다."""
        ai = load_settings(ROOT / "config.ai.example.json")
        for index, (settings, category) in enumerate(((ai, "기타"), (self.settings, None))):
            path = self.directory / f"input-{index}.xlsx"
            self.workbook([[category]], headers=["category"], path=path)
            output = self.directory / f"summary-{index}"
            summarize_file(path, output, settings)
            self.assertGreater((output / "chart.png").stat().st_size, 1000)

    def test_chart_failure_leaves_no_partial_output(self):
        """차트 저장이 실패하면 부분 집계 폴더를 완료 결과로 남기지 않는다."""
        self.workbook([["홍보"]], headers=["category"])
        output = self.directory / "summary"
        with patch("reporting.render_chart", side_effect=OSError()), self.assertRaises(OSError):
            summarize_file(self.input, output, self.settings)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.directory.glob(".survey-report-*")), [])
        self.assertFalse(output.with_name(output.name + ".lock").exists())

    def test_missing_font_does_not_publish_partial_report(self):
        """명시한 폰트가 없으면 오류를 숨기거나 불완전한 결과를 확정하지 않는다."""
        self.workbook([["홍보"]], headers=["category"])
        output = self.directory / "summary"
        with self.assertRaises(SurveyError):
            summarize_file(self.input, output, self.settings, font_path=self.directory / "missing.ttf")
        self.assertFalse(output.exists())


class CliTests(SyntheticCase):
    """새 프로세스에서 명령 연결·무부작용 import·오류 출력을 검증한다."""

    def test_help_and_import_do_not_need_dependencies_or_key(self):
        """도움말과 import는 원격 호출·입출력·환경 변경 없이 표준 라이브러리로 가능하다."""
        # 무부작용 확인을 위해 선택 라이브러리의 import 자체도 차단한다.
        bootstrap = """
import builtins, os, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    '''실행 의존성의 조기 import를 막는다.'''
    if name.split('.')[0] in {'openpyxl', 'langchain_openai', 'langchain_core', 'matplotlib', 'pydantic', 'dotenv'}:
        raise RuntimeError('unexpected dependency import')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
before = dict(os.environ)
import config, storage, labeling, reporting, survey
assert dict(os.environ) == before
raise SystemExit(survey.main(sys.argv[1:]))
"""
        result = self.process(["--help"], bootstrap=bootstrap)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("extract", result.stdout)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_extract_classify_summarize_connected_in_new_processes(self):
        """세 명령을 실제 가상 Excel로 연결하되 분류기만 대체한다."""
        self.workbook([["001", "first", "unused"], ["002", "second", None]], headers=["id", "answer", "extra"])
        config = self.config_file()
        extracted = self.directory / "extracted.xlsx"
        result = self.process(["extract", "--input", self.input, "--output", extracted, "--columns", "id", "answer"])
        self.assertEqual(result.returncode, 0, result.stderr)
        bootstrap = """
import sys, labeling, survey
def build(settings, key):
    '''새 프로세스에서 결정적인 가상 분류기를 제공한다.'''
    def classify(answer):
        '''가상 응답 순서에 따라 범주를 반환한다.'''
        return ['홍보', '신규개방'] if answer == 'first' else ['홍보']
    return classify
labeling.build_classifier = build
labeling.read_api_key = lambda path: 'test-only-key'
raise SystemExit(survey.main(sys.argv[1:]))
"""
        result = self.process(["classify", "--input", extracted, "--output", self.output, "--config", config], bootstrap=bootstrap)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.directory / "summary"
        result = self.process(["summarize", "--input", self.output, "--output", output, "--config", config])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(read_table(output / "summary.xlsx", "counts").rows,
                         [["홍보", 2, 66.7], ["신규개방", 1, 33.3]])
        self.assertEqual([row[0] for row in read_table(self.output).rows], [2, 3])

    def test_failure_exit_and_resume_in_new_process(self):
        """오류 종료 1·원문 차단·재개 후 완료 종료 0을 실제 프로세스로 확인한다."""
        self.workbook([[1, "first"], [2, "second"]])
        config = self.config_file()
        bootstrap = """
import sys, labeling, survey
def build(settings, key):
    '''첫 실행의 두 번째 행 실패와 재개 성공을 모의한다.'''
    def classify(answer):
        '''재개 전 가상 비밀문구를 포함한 원격 오류를 발생시킨다.'''
        if answer == 'second' and '--resume' not in sys.argv:
            raise RuntimeError('PRIVATE_RESPONSE test-secret')
        if answer == 'first' and '--resume' in sys.argv:
            raise AssertionError('completed row was called again')
        return ['홍보']
    return classify
labeling.build_classifier = build
labeling.read_api_key = lambda path: 'test-only-key'
raise SystemExit(survey.main(sys.argv[1:]))
"""
        arguments = ["classify", "--input", self.input, "--output", self.output, "--config", config]
        result = self.process(arguments, bootstrap=bootstrap)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("PRIVATE_RESPONSE", result.stdout + result.stderr)
        self.assertNotIn("test-secret", result.stdout + result.stderr)
        result = self.process(arguments + ["--resume"], bootstrap=bootstrap)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([row[-2] for row in read_table(self.output).rows], ["completed", "completed"])

    def test_all_blank_classification_cli_without_key(self):
        """응답이 비어 있는 파일은 실제 CLI에서도 키 없이 저장한다."""
        self.workbook([[1, None]])
        result = self.process(["classify", "--input", self.input, "--output", self.output,
                               "--config", self.config_file()])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(read_table(self.output).rows[0][-2], "skipped")

    def test_missing_key_and_existing_output_exit_two(self):
        """설정 오류와 기존 결과 보호는 실행 실패 종료 2로 구분한다."""
        self.workbook([[1, "가상 응답"]])
        arguments = ["classify", "--input", self.input, "--output", self.output,
                     "--config", self.config_file()]
        result = self.process(arguments)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.output.exists())
        self.output.write_bytes(b"preserve")
        result = self.process(arguments)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.output.read_bytes(), b"preserve")
