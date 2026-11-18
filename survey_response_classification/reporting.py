"""검토된 응답의 범주 빈도와 분모를 집계하고 두 방식의 그래프 차이를 보존한다."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile

from config import Settings, SurveyError
from labeling import InvalidResult, STATES, parse_labels
from storage import Table, check_new_path, output_lock, read_table, write_workbook


@dataclass
class Summary:
    """범주별 건수와 응답 수·할당 수·미집계 상태를 함께 담는다."""

    counts: list[tuple[str, int]]
    response_count: int
    assignment_count: int
    omitted: dict[str, int]
    mode: str

    @property
    def denominator(self) -> int:
        """일반 의견은 범주 할당 수, AI 수요는 유효 분류 응답 수를 반환한다."""
        return self.assignment_count if self.mode == "general" else self.response_count

    def count_rows(self) -> list[list]:
        """기존 모드별 컬럼 이름과 반올림 차이를 유지한 집계표를 반환한다."""
        header = ["category", "개수", "퍼센트"] if self.mode == "general" else ["category", "count", "percent"]
        rows = [header]
        for category, count in self.counts:
            percent = count / self.denominator * 100
            rows.append([category, count, round(percent, 1) if self.mode == "general" else percent])
        return rows

    def detail_rows(self) -> list[list]:
        """집계 분모와 제외 상태를 별도 시트에 명시한다."""
        return [["항목", "값"], ["분류 방식", self.mode], ["분류된 응답 수", self.response_count],
                ["범주 할당 수", self.assignment_count],
                ["비율 분모", "범주 할당 건수" if self.mode == "general" else "분류된 응답 건수"],
                ["분모 건수", self.denominator], ["집계표 기타 포함", "포함"],
                ["그래프 기타 포함", "포함" if self.mode == "general" else "제외"]] + [
                    [f"미집계: {status}", count] for status, count in sorted(self.omitted.items())]


def aggregate(table: Table, settings: Settings) -> Summary:
    """유효한 분류만 집계하며 잘못된 범주를 임의로 합치거나 누락하지 않는다."""
    if "category" not in table.headers:
        raise SurveyError("집계 입력에 category 컬럼이 필요합니다.")
    category_index = table.headers.index("category")
    status_index = table.headers.index("status") if "status" in table.headers else None
    counts = Counter()
    omitted = Counter()
    response_count = 0
    for row in table.rows:
        category = row[category_index]
        blank = category is None or (isinstance(category, str) and not category.strip())
        if status_index is not None:
            status = row[status_index]
            if status not in STATES:
                raise SurveyError("집계 입력에 알 수 없는 처리 상태가 있습니다.")
            if status != "completed":
                if not blank:
                    raise SurveyError("미완료 행에 분류값이 있습니다. 검토 후 상태를 completed로 확정하세요.")
                omitted[status] += 1
                continue
        elif blank:
            omitted["blank_category"] += 1
            continue
        try:
            labels = parse_labels(category, settings)
        except InvalidResult:
            raise SurveyError("집계 입력에 비어 있거나 허용되지 않은 분류값이 있습니다.") from None
        counts.update(labels)
        response_count += 1
    return Summary(counts.most_common(), response_count, sum(counts.values()), dict(omitted), settings.mode)


def choose_font(font_path: str | Path | None):
    """명시한 폰트 또는 설치된 한국어 폰트를 선택하며 잘못된 경로를 숨기지 않는다."""
    from matplotlib import font_manager

    if font_path is not None:
        path = Path(font_path)
        if not path.is_file():
            raise SurveyError("지정한 폰트 파일이 없습니다.")
        return font_manager.FontProperties(fname=str(path))
    original = Path("C:/Windows/Fonts/H2HDRM.ttf")
    if original.is_file():
        return font_manager.FontProperties(fname=str(original))
    installed = {font.name for font in font_manager.fontManager.ttflist}
    for name in ("Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR"):
        if name in installed:
            return font_manager.FontProperties(family=name)
    raise SurveyError("한국어 폰트를 찾지 못했습니다. --font로 폰트 파일을 지정하세요.")


def render_chart(summary: Summary, path: Path, font_path: str | Path | None = None,
                 *, show: bool = False) -> None:
    """일반 원형 차트와 기타를 제외한 AI 막대 차트를 PNG로 저장하고 선택 시 표시한다."""
    import matplotlib

    if not show:
        matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    font = choose_font(font_path)
    figure, axes = plt.subplots(figsize=(6, 6))
    try:
        counts = [(name, count) for name, count in summary.counts
                  if summary.mode == "general" or name != "기타"]
        if not counts:
            text = "기타를 제외한 응답 없음" if summary.mode == "ai" else "분류된 응답 없음"
            axes.text(0.5, 0.5, text, ha="center", va="center", fontproperties=font)
            axes.set_axis_off()
        elif summary.mode == "general":
            axes.pie([count for _, count in counts], labels=[name for name, _ in counts],
                     autopct="%1.1f%%", startangle=90, counterclock=False,
                     textprops={"fontproperties": font, "fontsize": 12})
        else:
            positions = list(range(len(counts)))
            axes.bar(positions, [count for _, count in counts])
            axes.set_xticks(positions, [name for name, _ in counts], rotation=45,
                           ha="right", fontproperties=font)
            axes.set_title("AI 학습데이터 수요(기타 제외)", fontproperties=font)
        figure.tight_layout()
        figure.savefig(path, dpi=150, bbox_inches="tight")
        if show:
            plt.show()
    finally:
        plt.close(figure)


def summarize_file(input_path: str | Path, output_path: str | Path, settings: Settings,
                   *, sheet: str | int = 0, font_path: str | Path | None = None,
                   show: bool = False) -> Summary:
    """집계표와 차트가 모두 작성된 경우에만 새 결과 폴더를 확정한다."""
    output = check_new_path(output_path)
    summary = aggregate(read_table(input_path, sheet), settings)
    with output_lock(output):
        check_new_path(output)
        temporary = Path(tempfile.mkdtemp(prefix=".survey-report-", dir=output.parent))
        try:
            write_workbook(temporary / "summary.xlsx", {
                "counts": summary.count_rows(), "details": summary.detail_rows(),
            })
            render_chart(summary, temporary / "chart.png", font_path, show=show)
            check_new_path(output)
            temporary.rename(output)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return summary
