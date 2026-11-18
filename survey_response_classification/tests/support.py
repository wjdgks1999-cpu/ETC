"""실제 응답·비밀값 없이 가상 Excel과 네트워크 차단 환경을 제공한다."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from config import load_settings
from storage import write_workbook


ROOT = Path(__file__).resolve().parents[1]


def deny_network(*args, **kwargs):
    """테스트 중 실수로 실제 네트워크에 접근하면 즉시 실패시킨다."""
    raise AssertionError("테스트에서는 실제 네트워크 호출을 허용하지 않습니다.")


def clean_environment() -> dict[str, str]:
    """실제 API·추적 설정을 제거한 새 프로세스용 환경을 반환한다."""
    return {key: value for key, value in os.environ.items()
            if not key.startswith(("OPENAI_", "LANGCHAIN_", "LANGSMITH_"))}


class SyntheticCase(unittest.TestCase):
    """매 테스트를 임시 폴더와 비밀값 없는 환경으로 격리한다."""

    def setUp(self):
        """가상 작업 경로를 마련하고 직접 HTTP 전송과 소켓 연결을 차단한다."""
        self.temporary = tempfile.TemporaryDirectory(prefix="etc-survey-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.settings = replace(load_settings(ROOT / "config.general.example.json"),
                                question="가상 설문 질문", answer_column="answer", id_column="id")
        self.input = self.directory / "input.xlsx"
        self.output = self.directory / "result.xlsx"
        self.env = clean_environment()
        self.env["MPLCONFIGDIR"] = str(self.directory / "mpl-cache")
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env["PYTHONIOENCODING"] = "utf-8"
        self.enterContext(patch.dict(os.environ, self.env, clear=True))
        self.enterContext(patch("socket.socket.connect", side_effect=deny_network))
        self.enterContext(patch("httpx.HTTPTransport.handle_request", side_effect=deny_network))

    def workbook(self, rows, *, headers=None, path=None, sheet="responses"):
        """가상 셀만 담긴 Excel을 만들고 경로를 반환한다."""
        path = path or self.input
        write_workbook(path, {sheet: [headers or ["id", "answer"]] + rows})
        return path

    def config_file(self, *, mode="general", **changes):
        """실제 기관·응답을 포함하지 않는 명령 시험용 JSON을 만든다."""
        data = {"mode": mode, "question": "가상 설문 질문", "answer_column": "answer", "id_column": "id"}
        data.update(changes)
        path = self.directory / "config.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def process(self, arguments, *, bootstrap=None):
        """새 Python 프로세스도 소켓을 차단한 상태에서 실제 명령을 실행한다."""
        code = """
import socket
def deny(*args, **kwargs):
    '''실제 소켓 전송을 차단한다.'''
    raise RuntimeError('network disabled')
socket.socket.connect = deny
""" + (bootstrap or "import sys, survey\nraise SystemExit(survey.main(sys.argv[1:]))")
        return subprocess.run([sys.executable, "-B", "-c", code, *map(str, arguments)],
                              cwd=ROOT, env=self.env, capture_output=True, text=True,
                              encoding="utf-8", timeout=60)
