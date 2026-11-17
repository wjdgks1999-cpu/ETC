"""가상 API와 별도 프로세스로 실제 명령의 입출력·종료 코드를 검증한다."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    """실제 키나 기존 업무 자료에 접근하지 않는 명령 테스트다."""

    def setUp(self):
        """가상 입력과 외부 실행 디렉터리를 준비한다."""
        temporary = tempfile.TemporaryDirectory(prefix="document-cli-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.input = self.directory / "example.hwpx"
        self.input.write_bytes(b"FAKE_INPUT")
        self.output = self.directory / "output"

    def command(self, mode="success", fixture=True, extra=None):
        """환경의 실제 API 키를 제거하고 새 프로세스에서 명령을 실행한다."""
        environment = {key: value for key, value in os.environ.items() if key != "UPSTAGE_API_KEY"}
        environment.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", PARSER_TEST_MODE=mode)
        script = ROOT / "tests/cli_fixture.py" if fixture else ROOT / "parse.py"
        arguments = extra if extra is not None else ["--input", str(self.input), "--output", str(self.output)]
        return subprocess.run([sys.executable, "-B", str(script), *arguments], cwd=self.directory,
                              env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)

    def test_help_without_key_or_output(self):
        """키 없이 도움말을 보고 결과 파일도 생성하지 않는다."""
        result = self.command(fixture=False, extra=["--help"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--input", result.stdout)
        self.assertFalse(self.output.exists())

    def test_import_without_key_has_no_side_effect(self):
        """모듈 import가 키 조회·환경 변경·파일 생성을 하지 않는다."""
        code = ("import os,sys; sys.path.insert(0,sys.argv[1]); "
                "os.environ.pop('UPSTAGE_API_KEY',None); before=dict(os.environ); "
                "import config,parse,client,storage; assert dict(os.environ)==before")
        result = subprocess.run([sys.executable, "-B", "-c", code, str(ROOT)], cwd=self.directory,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.directory.iterdir()), [self.input])

    def test_success_and_repeat_preserves_result(self):
        """정상 결과를 저장한 뒤 같은 경로의 재실행을 거부한다."""
        first = self.command()
        self.assertEqual(first.returncode, 0, first.stderr)
        manifest = json.loads((self.output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["written_page_count"], 2)
        before = (self.output / "manifest.json").read_bytes()
        again = self.command()
        self.assertEqual(again.returncode, 2)
        self.assertNotIn("파싱 요청", again.stdout)
        self.assertEqual((self.output / "manifest.json").read_bytes(), before)

    def test_review_result_uses_original_pages_and_exit_one(self):
        """누락 가능 페이지가 있으면 결과와 검토 필요 종료 코드를 남긴다."""
        result = self.command("review")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue((self.output / "parsing_page_3.md").exists())
        self.assertFalse((self.output / "parsing_page_2.md").exists())
        self.assertIn("검토 항목", result.stdout)

    def test_api_failure_and_empty_response_leave_no_output(self):
        """API 실패와 빈 응답은 성공 메시지·결과 폴더를 남기지 않는다."""
        for mode in ("error", "empty"):
            with self.subTest(mode=mode):
                result = self.command(mode)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.output.exists())
                self.assertNotIn("저장 완료", result.stdout)
                self.assertNotIn("fake-key-for-cli", result.stdout + result.stderr)
                self.assertNotIn("FAKE_PRIVATE_RESPONSE", result.stdout + result.stderr)

    def test_missing_key_and_invalid_input_do_not_call_service(self):
        """키 누락과 없는 입력은 전송 전에 명확한 실패로 끝난다."""
        result = self.command(fixture=False)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("파싱 요청", result.stdout)
        result = self.command(extra=["--input", str(self.directory / "missing.hwpx"), "--output", str(self.output)])
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("파싱 요청", result.stdout)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
