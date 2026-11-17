"""입력 경로와 검토 실행 설정을 정의한다."""

from dataclasses import dataclass
from pathlib import Path

from .schemas import InputError

BASE_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ReviewConfig:
    """입력 파일·시트, 모델과 병렬 처리 범위를 보관한다."""

    tables: Path = BASE_DIR / "테이블정보.xlsx"
    columns: Path = BASE_DIR / "컬럼정보.xlsx"
    table_sheet: str | None = None
    column_sheet: str | None = None
    limit: int | None = None
    max_concurrency: int = 5
    output_dir: Path = BASE_DIR / "outputs"
    output: Path | None = None
    overwrite: bool = False
    model: str | None = None
    env_file: Path = BASE_DIR / ".env"
    prompt_dir: Path = BASE_DIR / "prompt"

    def __post_init__(self):
        """경로를 정리하고 실행 범위·출력 형식을 검증한다."""
        for name in ("tables", "columns", "output_dir", "env_file", "prompt_dir"):
            object.__setattr__(self, name, Path(getattr(self, name)))
        if self.output is not None:
            object.__setattr__(self, "output", Path(self.output))
            if self.output.suffix.lower() != ".xlsx":
                raise InputError("검토 결과의 출력 경로는 .xlsx 형식이어야 합니다.")
            if self.output.resolve() in (self.tables.resolve(), self.columns.resolve()):
                raise InputError("출력 경로는 원본 파일과 달라야 합니다.")
        if self.max_concurrency < 1 or (self.limit is not None and self.limit < 1):
            raise InputError("동시 처리 수와 처리 한도는 1 이상의 정수여야 합니다.")
