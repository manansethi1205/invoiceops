import os
import shutil
import subprocess
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict


class OcrRuntimeInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool
    engine: str = "tesseract"
    version: str | None = None
    tessdata_prefix: str | None = None


class OcrRuntimeUnavailableError(RuntimeError):
    pass


def inspect_ocr_runtime(
    *,
    executable: str = "tesseract",
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> OcrRuntimeInfo:
    tessdata_prefix = os.environ.get("TESSDATA_PREFIX")
    resolved = shutil.which(executable)
    if resolved is None:
        return OcrRuntimeInfo(available=False, tessdata_prefix=tessdata_prefix)
    try:
        version_result = command_runner(
            [resolved, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        language_result = command_runner(
            [resolved, "--list-langs"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return OcrRuntimeInfo(available=False, tessdata_prefix=tessdata_prefix)
    output = version_result.stdout or version_result.stderr
    first_line = output.splitlines()[0].strip() if output.splitlines() else None
    languages = {line.strip() for line in language_result.stdout.splitlines()}
    return OcrRuntimeInfo(
        available=(
            version_result.returncode == 0
            and language_result.returncode == 0
            and "eng" in languages
        ),
        version=first_line,
        tessdata_prefix=tessdata_prefix,
    )


def require_ocr_runtime(info: OcrRuntimeInfo) -> None:
    if info.available:
        return
    raise OcrRuntimeUnavailableError(
        "OCR examples are present, but the Tesseract runtime is unavailable. "
        "Run this evaluation using the Docker evaluation profile."
    )
