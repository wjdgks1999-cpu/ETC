"""가상 입력과 실제 네트워크 차단 환경을 제공한다."""

import csv
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
    """실제 네트워크 전송 시도를 즉시 실패시킨다."""
    raise AssertionError("테스트에서는 실제 네트워크를 사용할 수 없습니다.")


def clean_environment() -> dict[str, str]:
    """실제 API와 추적 설정을 제거한 환경을 반환한다."""
    return {key: value for key, value in os.environ.items()
            if not key.startswith(("OPENAI_", "LANGCHAIN_", "LANGSMITH_"))}


class SyntheticCase(unittest.TestCase):
    """입출력을 임시 폴더에 격리하고 실제 키·네트워크 사용을 차단한다."""

    def setUp(self):
        """매 시험에 별도 경로와 가상 작업 설정을 준비한다."""
        self.temporary = tempfile.TemporaryDirectory(prefix="etc-cleaning-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.input = self.directory / "input.xlsx"
        self.output = self.directory / "output.xlsx"
        self.env = clean_environment()
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env["PYTHONIOENCODING"] = "utf-8"
        self.enterContext(patch.dict(os.environ, self.env, clear=True))
        self.enterContext(patch("socket.socket.connect", side_effect=deny_network))
        self.enterContext(patch("httpx.HTTPTransport.handle_request", side_effect=deny_network))
        self.settings = replace(load_settings("html"), column="body")

    def workbook(self, rows, *, headers=None, path=None, sheet="data"):
        """가상 Excel을 생성하며 업무 자료를 사용하지 않는다."""
        path = path or self.input
        write_workbook(path, {sheet: [headers or ["id", "body"]] + rows})
        return path

    def csv_file(self, rows, *, headers=None, encoding="cp949", path=None):
        """따옴표·쉼표·줄바꿈을 포함할 수 있는 가상 CSV를 만든다."""
        path = path or self.directory / "input.csv"
        with path.open("w", encoding=encoding, newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(headers or ["id", "body"])
            writer.writerows(rows)
        return path

    def config_file(self, **changes):
        """명령 시험용 JSON을 생성한다."""
        data = {"column": "body"}
        data.update(changes)
        path = self.directory / "config.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def process(self, arguments, *, bootstrap=None):
        """새 프로세스에서도 소켓을 차단한 상태로 실제 명령을 실행한다."""
        code = """
import socket
def deny(*args, **kwargs):
    '''실제 네트워크 연결을 차단한다.'''
    raise RuntimeError('network disabled')
socket.socket.connect = deny
""" + (bootstrap or "import sys, clean\nraise SystemExit(clean.main(sys.argv[1:]))")
        return subprocess.run([sys.executable, "-B", "-c", code, *map(str, arguments)],
                              cwd=ROOT, env=self.env, capture_output=True, text=True,
                              encoding="utf-8", timeout=60)
