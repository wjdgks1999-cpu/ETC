"""페이지와 검토 정보를 임시 폴더에 완성한 뒤 새 결과 폴더로 확정한다."""

from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import tempfile
from urllib.parse import urlsplit

from config import ParseError


class ImageSources(HTMLParser):
    """HTML 이미지 참조만 수집하고 문서의 코드를 실행하거나 URL에 접속하지 않는다."""

    def __init__(self):
        """이미지 주소 목록과 표준 HTML 파서를 초기화한다."""
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        """이미지 요소의 src 속성만 기록한다."""
        if tag.lower() == "img":
            self.sources.append(dict(attrs).get("src") or "")


def image_reference_summary(content):
    """일반 Markdown·HTML 이미지 참조를 로컬 누락·외부 미확인·인라인으로 분류한다."""
    parser = ImageSources()
    parser.feed(content)
    targets = list(parser.sources)
    inline = re.compile(r"!\[[^\]]*\]\(\s*(?:<([^>]*)>|([^\s)]*))[^)]*\)")
    targets.extend(first or second for first, second in inline.findall(content))
    definitions = dict(re.findall(r"^\s*\[([^\]]+)\]:\s*<?([^\s>]+)>?", content, re.MULTILINE))
    for label, identifier in re.findall(r"!\[([^\]]*)\]\[([^\]]*)\]", content):
        targets.append(definitions.get(identifier or label, ""))
    counts = {"unresolved_local": 0, "external_unchecked": 0, "inline_data": 0}
    for target in targets:
        target = target.strip()
        if target.lower().startswith("data:image/"):
            counts["inline_data"] += 1
        else:
            try:
                remote = target.startswith("//") or urlsplit(target).scheme.lower() in {"http", "https"}
            except ValueError:
                remote = False
            # 이번 출력은 Markdown과 명세서뿐이므로 로컬 이미지 파일은 만들어지지 않는다.
            counts["external_unchecked" if remote else "unresolved_local"] += 1
    return counts


def package_versions():
    """재실행 비교에 필요한 Python과 직접 의존성 버전을 반환한다."""
    versions = {"python": platform.python_version()}
    for package in ("httpx", "pypdf", "python-dotenv"):
        versions[package] = importlib.metadata.version(package)
    return versions


def write_text(path, content):
    """UTF-8과 고정 개행으로 내용을 새 파일에만 기록한다."""
    with path.open("x", encoding="utf-8", newline="") as stream:
        stream.write(content)


def save_result(source, result, settings):
    """완성한 페이지·manifest만 게시하며 오류가 나면 임시 결과를 정리한다."""
    output = settings.output_path
    if os.path.lexists(output):
        raise ParseError("출력 경로가 이미 존재합니다. 기존 결과는 보존했습니다.")
    numbers = [page.number for page in result.pages]
    if (not numbers or len(set(numbers)) != len(numbers)
            or any(type(number) is not int or number < 1 for number in numbers)):
        raise ParseError("저장할 페이지 번호가 비었거나 중복·오류가 있습니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    issues = list(result.issues)
    records = []
    with tempfile.TemporaryDirectory(prefix=".document-parse-", dir=output.parent) as temporary:
        staging = Path(temporary) / "result"
        staging.mkdir()
        for page in result.pages:
            filename = f"parsing_page_{page.number}.md"
            write_text(staging / filename, page.content)
            images = image_reference_summary(page.content)
            if images["unresolved_local"] or images["external_unchecked"]:
                issues.append({"code": "image_references_need_review", "page": page.number, **images})
            records.append({
                "source_page": page.number, "file": filename,
                "sha256": hashlib.sha256(page.content.encode("utf-8")).hexdigest(),
                "element_count": page.element_count, "coordinates": page.coordinates,
                "image_references": images,
            })
        manifest = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "review_required" if issues else "complete",
            "source": {"name": source.name, "sha256": source.sha256,
                       "bytes": len(source.content), "total_pages": result.total_pages},
            "request": {"model": settings.model, "ocr": settings.ocr, "output_format": "markdown",
                        "chart_recognition": True, "coordinates": True, "base64_encoding": [],
                        "timeout_seconds": settings.timeout,
                        "pdf_per_page": source.pdf is not None, "count": result.request_count},
            "response_models": result.response_models,
            "written_page_count": len(records), "missing_pages": result.missing_pages,
            "pages": records, "issues": issues, "versions": package_versions(),
        }
        write_text(staging / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        if os.path.lexists(output):
            raise ParseError("저장 중 출력 경로가 생겼습니다. 기존 결과는 보존했습니다.")
        try:
            # 같은 상위 폴더에서 이동하며 Windows에서는 기존 폴더를 교체하지 않는다.
            staging.rename(output)
        except FileExistsError as error:
            raise ParseError("저장 중 출력 경로가 생겼습니다. 기존 결과는 보존했습니다.") from error
    return manifest
