"""임시 파일로 설정·명세서·이미지 참조·결과 보존을 검증한다."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from client import Page, ParseResult, read_source
from config import ParseError, Settings, load_api_key, validate_settings
from storage import image_reference_summary, save_result, write_text


class StorageConfigTests(unittest.TestCase):
    """가상 원본과 출력 후보를 매번 새 임시 디렉터리에 둔다."""

    def setUp(self):
        """업무 데이터가 없는 로컬 시험 자료를 준비한다."""
        temporary = tempfile.TemporaryDirectory(prefix="document-storage-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.input = self.directory / "example.hwpx"
        self.input.write_bytes(b"FAKE_SOURCE")
        self.settings = Settings(self.input, self.directory / "output")
        self.source = read_source(self.input)
        self.result = ParseResult([Page(5, "가상 본문\n두 번째 줄", 1), Page(9, "가상 표", 2)],
                                  9, 1, ["document-parse-fixture"], [1, 2, 3, 4, 6, 7, 8],
                                  [{"code": "pages_without_elements", "pages": [1, 2, 3, 4, 6, 7, 8]}])

    def test_settings_defaults_and_paths(self):
        """기본 모델·OCR·시간 제한과 경로 해석을 확인한다."""
        checked = validate_settings(self.settings)
        self.assertEqual((checked.model, checked.ocr, checked.timeout), ("document-parse", "force", 300))
        self.assertEqual(checked.input_path, self.input.resolve())
        self.assertEqual(checked.output_path, self.settings.output_path.resolve())

    def test_invalid_options_and_missing_input(self):
        """옵션 오류와 없는 입력을 전송 전에 거부한다."""
        settings = [replace(self.settings, timeout=value) for value in (0, -1, float("nan"), float("inf"))]
        settings += [replace(self.settings, model=" "), replace(self.settings, ocr="bad"),
                     replace(self.settings, input_path=self.directory / "missing.hwpx"),
                     replace(self.settings, env_file=self.directory / "missing.env")]
        for setting in settings:
            with self.subTest(setting=setting), self.assertRaises(ParseError):
                validate_settings(setting)

    def test_empty_input_and_unsupported_suffix(self):
        """빈 입력과 지원 목록 밖의 파일을 거부한다."""
        self.input.write_bytes(b"")
        with self.assertRaises(ParseError):
            validate_settings(self.settings)
        other = self.directory / "input.exe"
        other.write_bytes(b"fake")
        with self.assertRaises(ParseError):
            validate_settings(replace(self.settings, input_path=other))

    def test_existing_output_and_file_parent_are_rejected(self):
        """기존 빈 출력 폴더도 보존하고 파일 아래의 잘못된 경로를 거부한다."""
        self.settings.output_path.mkdir()
        with self.assertRaises(ParseError):
            validate_settings(self.settings)
        with self.assertRaises(ParseError):
            validate_settings(replace(self.settings, output_path=self.input / "child"))

    def test_environment_precedence_without_mutation(self):
        """환경 변수 키가 파일보다 우선하며 프로세스 환경을 바꾸지 않는다."""
        env_file = self.directory / "fake.env"
        env_file.write_text('UPSTAGE_API_KEY=fake-file-key\n', encoding="utf-8")
        with patch.dict(os.environ, {"UPSTAGE_API_KEY": "fake-environment-key"}):
            before = dict(os.environ)
            self.assertEqual(load_api_key(env_file), "fake-environment-key")
            self.assertEqual(dict(os.environ), before)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(load_api_key(env_file), "fake-file-key")
            self.assertNotIn("UPSTAGE_API_KEY", os.environ)

    def test_key_missing_and_invalid_are_safe_errors(self):
        """없거나 줄바꿈을 포함한 키를 비밀값 없는 오류로 알린다."""
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ParseError):
            load_api_key()
        with patch.dict(os.environ, {"UPSTAGE_API_KEY": "FAKE_PRIVATE\nVALUE"}):
            with self.assertRaises(ParseError) as caught:
                load_api_key()
        self.assertNotIn("FAKE_PRIVATE", str(caught.exception))

    def test_source_snapshot_stays_consistent(self):
        """읽은 뒤 원본 경로가 바뀌어도 전송 스냅샷과 기록 해시는 일치한다."""
        original = self.source.content
        self.input.write_bytes(b"LATER_FAKE_CONTENT")
        self.assertEqual(self.source.content, original)
        self.assertEqual(self.source.sha256, hashlib.sha256(original).hexdigest())

    def test_manifest_and_original_page_filenames(self):
        """원본 번호·좌표·해시·요청 설정을 페이지와 연결해 저장한다."""
        self.result.pages[0].coordinates = [[{"x": 0.1, "y": 0.2}]]
        manifest = save_result(self.source, self.result, self.settings)
        output = self.settings.output_path
        self.assertEqual({p.name for p in output.iterdir()}, {"parsing_page_5.md", "parsing_page_9.md", "manifest.json"})
        restored = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(restored, manifest)
        self.assertEqual(restored["status"], "review_required")
        self.assertEqual(restored["source"]["sha256"], self.source.sha256)
        self.assertNotIn("api_key", json.dumps(restored))
        self.assertNotIn(str(self.directory), json.dumps(restored))
        for page in restored["pages"]:
            data = (output / page["file"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), page["sha256"])
        self.assertEqual((output / "parsing_page_5.md").read_bytes(), self.result.pages[0].content.encode("utf-8"))

    def test_completed_result_is_never_overwritten(self):
        """재실행해도 기존 완료 결과의 파일 내용은 바뀌지 않는다."""
        save_result(self.source, self.result, self.settings)
        before = {p.name: p.read_bytes() for p in self.settings.output_path.iterdir()}
        self.result.pages[0].content = "새 가상 결과"
        with self.assertRaises(ParseError):
            save_result(self.source, self.result, self.settings)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.settings.output_path.iterdir()})

    def test_partial_write_failure_leaves_no_result(self):
        """두 번째 파일 저장 실패 시 첫 파일도 최종 결과에 남지 않는다."""
        def fail_second(path, content):
            """가상 저장 오류를 한 페이지에서 발생시킨다."""
            if path.name == "parsing_page_9.md":
                raise OSError("FAKE_DISK_FAILURE")
            write_text(path, content)

        with patch("storage.write_text", side_effect=fail_second), self.assertRaises(OSError):
            save_result(self.source, self.result, self.settings)
        self.assertFalse(self.settings.output_path.exists())
        self.assertFalse(list(self.directory.glob(".document-parse-*")))
        self.assertEqual(self.input.read_bytes(), b"FAKE_SOURCE")

    def test_manifest_failure_leaves_no_result(self):
        """명세서 작성에 실패한 결과도 완료 폴더로 공개하지 않는다."""
        def fail_manifest(path, content):
            """명세서 저장만 실패시킨다."""
            if path.name == "manifest.json":
                raise OSError("FAKE_MANIFEST_FAILURE")
            write_text(path, content)

        with patch("storage.write_text", side_effect=fail_manifest), self.assertRaises(OSError):
            save_result(self.source, self.result, self.settings)
        self.assertFalse(self.settings.output_path.exists())
        self.assertFalse(list(self.directory.glob(".document-parse-*")))

    def test_publish_race_preserves_other_output(self):
        """저장 확정 직전 다른 작업이 만든 폴더를 덮어쓰지 않는다."""
        original_rename = Path.rename

        def create_competing_result(path, destination):
            """다른 실행이 만든 결과가 먼저 존재하는 상황을 재현한다."""
            destination.mkdir()
            (destination / "keep.txt").write_text("OTHER_RESULT", encoding="utf-8")
            return original_rename(path, destination)

        with patch("storage.Path.rename", new=create_competing_result), self.assertRaises((ParseError, OSError)):
            save_result(self.source, self.result, self.settings)
        self.assertEqual((self.settings.output_path / "keep.txt").read_text(), "OTHER_RESULT")
        self.assertFalse(list(self.directory.glob(".document-parse-*")))

    def test_invalid_page_numbers_cannot_make_paths(self):
        """페이지 번호로 출력 경로를 탈출하거나 중복 저장할 수 없다."""
        for pages in ([Page("../other", "fake", 1)], [Page(1, "a", 1), Page(1, "b", 1)], []):
            with self.subTest(pages=pages), self.assertRaises(ParseError):
                save_result(self.source, replace(self.result, pages=pages), self.settings)
        self.assertFalse(self.settings.output_path.exists())

    def test_image_reference_categories(self):
        """일반 Markdown·HTML·참조형·인라인 이미지를 구분한다."""
        content = ('![local](figure.png) ![remote](https://example.invalid/figure.png) '
                   '![inline](data:image/png;base64,AAAA) <img src="local2.png"> '
                   '![reference][fig]\n[fig]: missing.png\n')
        self.assertEqual(image_reference_summary(content),
                         {"unresolved_local": 3, "external_unchecked": 1, "inline_data": 1})

    def test_broken_image_syntax_does_not_abort_saving(self):
        """잘못된 URL과 비어 있는 참조는 원문을 보존한 채 검토 대상으로 남긴다."""
        content = '![bad](http://[broken) ![empty]()'
        self.result.pages[0].content = content
        manifest = save_result(self.source, self.result, self.settings)
        self.assertTrue(any(issue["code"] == "image_references_need_review" for issue in manifest["issues"]))
        self.assertEqual((self.settings.output_path / "parsing_page_5.md").read_text(encoding="utf-8"), content)


if __name__ == "__main__":
    unittest.main()
