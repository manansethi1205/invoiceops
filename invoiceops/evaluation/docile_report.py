import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocileModeMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["end_to_end", "precomputed_ocr"]
    document_count: int = Field(gt=0)
    supported_subset_kile_f1: float = Field(ge=0, le=1)
    supported_subset_lir_f1: float = Field(ge=0, le=1)
    official_full_kile_f1: float = Field(ge=0, le=1)
    official_full_lir_f1: float = Field(ge=0, le=1)
    official_full_kile_ap: float = Field(ge=0, le=1)
    official_full_lir_ap: float = Field(ge=0, le=1)


class DocileAggregateReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    extractor_name: str
    extractor_version: str
    dataset: str = "DocILE"
    source_split: str = "val"
    sample_seed: int = 1205
    sample_manifest_sha256: str
    modes: list[DocileModeMetrics] = Field(min_length=2, max_length=2)


def render_docile_markdown(report: DocileAggregateReport) -> str:
    lines = [
        "# DocILE external baseline",
        "",
        "## Method",
        "",
        f"- Extractor: `{report.extractor_name}@{report.extractor_version}`",
        f"- Sample: fixed {report.modes[0].document_count}-document validation subset",
        f"- Sampling seed: {report.sample_seed}",
        "- End-to-end OCR: PyMuPDF embedded text with Tesseract fallback",
        "- Parsing-only OCR: DocILE precomputed OCR",
        "- AP is uncalibrated because this deterministic baseline emits no confidence scores.",
        "- A task with zero predictions is reported as zero for AP, precision, recall and F1; "
        "no placeholder predictions are introduced.",
        "",
        "## Supported fields",
        "",
        "KILE: document_id, date_issue, amount_total_net, amount_total_tax, "
        "amount_total_gross.",
        "",
        "LIR: line_item_description, line_item_quantity.",
        "",
        "## Results",
        "",
        "| Mode | Metric | Result |",
        "|---|---|---:|",
    ]
    labels = (
        ("supported_subset_kile_f1", "Supported-subset KILE F1"),
        ("supported_subset_lir_f1", "Supported-subset LIR F1"),
        ("official_full_kile_f1", "Official full KILE F1"),
        ("official_full_lir_f1", "Official full LIR F1"),
        ("official_full_kile_ap", "Official full KILE AP"),
        ("official_full_lir_ap", "Official full LIR AP"),
    )
    for mode in report.modes:
        mode_label = "End-to-end" if mode.mode == "end_to_end" else "Precomputed OCR"
        for key, label in labels:
            lines.append(f"| {mode_label} | {label} | {getattr(mode, key):.4f} |")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Supported-subset metrics cover only semantically mapped InvoiceOps fields. Full "
            "official metrics include every DocILE class and are expected to be lower.",
            "",
            "## Limitations",
            "",
            "The fixed sample is not the complete validation set. InvoiceOps does not encode "
            "gross-versus-net tax basis for line prices or amounts. Raw documents, OCR, "
            "predictions and evaluator matchings are deliberately excluded from this report.",
            "",
        ]
    )
    return "\n".join(lines)


def write_docile_aggregate_report(path: Path, report: DocileAggregateReport) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "report.json").write_text(
        json.dumps(report.model_dump(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (path / "report.md").write_text(render_docile_markdown(report), encoding="utf-8")
