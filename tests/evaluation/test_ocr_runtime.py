import subprocess

import pytest

from invoiceops.extraction.ocr_runtime import (
    OcrRuntimeInfo,
    OcrRuntimeUnavailableError,
    inspect_ocr_runtime,
    require_ocr_runtime,
)


def test_missing_tesseract_is_reported_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("invoiceops.extraction.ocr_runtime.shutil.which", lambda _: None)
    assert inspect_ocr_runtime().available is False


def test_tesseract_version_is_captured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("invoiceops.extraction.ocr_runtime.shutil.which", lambda _: "tesseract")

    def successful(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        output = "tesseract 5.5.0\n details" if "--version" in command else "eng\nosd\n"
        return subprocess.CompletedProcess(command, 0, output, "")

    info = inspect_ocr_runtime(command_runner=successful)
    assert info.available is True
    assert info.version == "tesseract 5.5.0"


def test_tesseract_without_english_language_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("invoiceops.extraction.ocr_runtime.shutil.which", lambda _: "tesseract")

    def without_english(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        output = "tesseract 5.5.0\n" if "--version" in command else "osd\n"
        return subprocess.CompletedProcess(command, 0, output, "")

    assert inspect_ocr_runtime(command_runner=without_english).available is False


def test_unavailable_runtime_has_actionable_error() -> None:
    with pytest.raises(OcrRuntimeUnavailableError, match="Docker evaluation profile"):
        require_ocr_runtime(OcrRuntimeInfo(available=False))
