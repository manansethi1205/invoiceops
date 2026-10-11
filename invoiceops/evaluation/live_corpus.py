"""Reproducible synthetic invoice assets; private scratch only, never provider output."""

import hashlib
import json
import random
import subprocess
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import pymupdf
from pydantic import BaseModel, ConfigDict

from invoiceops.evaluation.header_miss_audit import _no_links
from invoiceops.evaluation.schemas import GroundTruthInvoice, GroundTruthLineItem
from invoiceops.schemas.extraction import BoundingBox

CORPUS_VERSION = "synthetic-live-financial-roles-v1"
FAMILIES = {
    "development": ("grid", "roles", "missing", "summary"),
    "unseen": ("reordered", "stacked", "ambiguous", "scan"),
}
FEATURES = (
    "net_tax_gross",
    "summary_totals",
    "repeated_amounts",
    "missing_columns",
    "reordered_rows",
    "ocr",
    "ambiguous_layouts",
)


class CellLabel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    role: str
    row: int | None
    page: int
    bbox: BoundingBox
    value: str


@dataclass(frozen=True)
class CorpusCase:
    ordinal: int
    split: str
    family: str
    body: bytes
    content_type: str
    truth: GroundTruthInvoice
    labels: tuple[CellLabel, ...]
    purchase_order_lines: tuple[GroundTruthLineItem, ...]
    expected_review: bool
    pages: int

    @property
    def filename(self) -> str:
        return f"case-{self.ordinal:03d}.{'png' if self.content_type == 'image/png' else 'pdf'}"


class _Canvas:
    def __init__(self, page: Any) -> None:
        self.page = page
        self.labels: list[CellLabel] = []

    def print_cell(
        self,
        x: float,
        y: float,
        text: str,
        role: str | None = None,
        row: int | None = None,
        prefix: str = "",
    ) -> None:
        self.page.insert_text((x, y), prefix + text, fontsize=10, fontname="helv")
        if role is not None:
            start = x + pymupdf.get_text_length(prefix, fontsize=10)
            end = start + pymupdf.get_text_length(text, fontsize=10)
            self.labels.append(
                CellLabel(
                    role=role,
                    row=row,
                    page=self.page.number,
                    bbox=BoundingBox(
                        x0=start / 700,
                        y0=(y - 11) / 700,
                        x1=end / 700,
                        y1=(y + 4) / 700,
                    ),
                    value=text,
                )
            )


def generate_cases(seed: int) -> list[CorpusCase]:
    if not 0 <= seed <= 2**32 - 1:
        raise ValueError("Invalid synthetic seed")
    rng = random.Random(seed)
    cases: list[CorpusCase] = []
    for split, families in FAMILIES.items():
        for family in families:
            for variant in range(2):
                ordinal = len(cases)
                pdf: Any = pymupdf.open()  # type: ignore[no-untyped-call]
                page = pdf.new_page(width=700, height=700)
                labels: list[CellLabel] = []

                canvas = _Canvas(page)
                labels = canvas.labels
                print_cell = canvas.print_cell

                price = Decimal(rng.randint(13, 24))
                quantities = [Decimal(2), Decimal(3)]
                prices = [price, price + 4]
                if variant == 1:
                    quantities[1], prices[1] = quantities[0], prices[0]
                amounts = [q * p for q, p in zip(quantities, prices, strict=True)]
                subtotal = sum(amounts, Decimal(0))
                tax = subtotal * Decimal("0.20")
                truth_lines: list[GroundTruthLineItem] = []
                po_lines = tuple(
                    GroundTruthLineItem(
                        description=f"Synthetic component {'Alpha' if row == 0 else 'Beta'}",
                        quantity=quantities[row],
                        unit_price=prices[row],
                        line_total=amounts[row],
                    )
                    for row in range(2)
                )
                number = f"SYN-LIVE-{seed}-{ordinal}"
                for y, text, role, prefix in (
                    (40, number, "invoice_number", "Invoice number: "),
                    (60, "2026-10-11", "invoice_date", "Invoice date: "),
                    (80, "USD", "currency", "Currency: "),
                ):
                    print_cell(35, y, text, role, prefix=prefix)
                page.insert_text(
                    (35, 105), "SYNTHETIC TEST INVOICE - NO BUSINESS DOCUMENT", fontsize=10
                )
                columns = [35, 255, 330, 410, 490, 580]
                headings = [
                    "Description",
                    "Quantity",
                    "Unit price",
                    "Line total (net)",
                    "Tax amount",
                    "Gross amount",
                ]
                if family == "roles":
                    headings = ["Item", "Qty", "Unit cost", "Net line amount", "VAT", "Gross"]
                if family == "scan":
                    columns = [150, 35, 330, 430, 510, 600]
                    headings = ["Article", "Units", "Unit cost", "Net extended", "VAT", "Gross"]
                if family == "stacked":
                    for x, heading in zip(columns, headings, strict=True):
                        for j, part in enumerate(heading.split()):
                            print_cell(x, 125 + j * 13, part)
                else:
                    if family == "ambiguous":
                        headings[3:] = ["Amount A", "Amount B", "Amount C"]
                    for x, heading in zip(columns, headings, strict=True):
                        print_cell(x, 140, heading)
                order = [1, 0] if family == "reordered" else [0, 1]
                for position, row in enumerate(order):
                    if family == "reordered" and variant == 1 and position == 1:
                        page = pdf.new_page(width=700, height=700)
                        canvas.page = page
                        print_cell(35, 80, "Continued items")
                    y = 200 + position * 55 if page.number == 0 else 140
                    description = f"Synthetic component {'Alpha' if row == 0 else 'Beta'}"
                    values = [
                        description,
                        str(quantities[row]),
                        f"{prices[row]:.2f}",
                        f"{amounts[row]:.2f}",
                        f"{amounts[row] * Decimal('0.2'):.2f}",
                        f"{amounts[row] * Decimal('1.2'):.2f}",
                    ]
                    roles = [
                        "description",
                        "quantity",
                        "unit_price",
                        "line_total",
                        "tax_amount",
                        "gross_amount",
                    ]
                    for column, (x, value, role) in enumerate(
                        zip(columns, values, roles, strict=True)
                    ):
                        if family == "missing" and column == 2:
                            continue
                        if family == "ambiguous" and column >= 3:
                            role = "unknown_amount"
                        # A different financial column order in the reserved layout family.
                        if family == "reordered" and column >= 3:
                            x = columns[{3: 5, 4: 4, 5: 3}[column]]
                        print_cell(x, y, value, role, row)
                    truth_lines.append(
                        GroundTruthLineItem(
                            description=description,
                            quantity=quantities[row],
                            unit_price=None if family == "missing" else prices[row],
                            line_total=None if family == "ambiguous" else amounts[row],
                        )
                    )
                if family == "summary":
                    print_cell(
                        35, 330, f"{subtotal:.2f}", "summary_total", prefix="Summary amount: "
                    )
                    print_cell(35, 355, "Payment terms and delivery notes; no additional items")
                for y, amount_value, role, prefix in (
                    (470, subtotal, "subtotal", "Subtotal: "),
                    (495, tax, "tax", "Tax: "),
                    (520, subtotal + tax, "total", "Total: "),
                ):
                    print_cell(360, y, f"{amount_value:.2f}", role, prefix=prefix)
                # Correct reordered headings too: the monetary roles are printed, not inferred.
                if family == "reordered":
                    first = pdf[0]
                    first.add_redact_annot(pymupdf.Rect(405, 125, 690, 145))  # type: ignore[no-untyped-call]
                    first.apply_redactions()
                    for x, heading in zip(columns[3:], headings[3:][::-1], strict=True):
                        first.insert_text((x, 140), heading, fontsize=10)
                body = (
                    pdf[0].get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("png")  # type: ignore[no-untyped-call]
                    if family == "scan"
                    else pdf.tobytes(no_new_id=True, deflate=True)
                )
                truth = GroundTruthInvoice(
                    invoice_number=number,
                    invoice_date=date(2026, 10, 11),
                    currency="USD",
                    subtotal=subtotal,
                    tax=tax,
                    total=subtotal + tax,
                    # Label row identities are Alpha/Beta, independent of printed row order.
                    line_items=sorted(truth_lines, key=lambda line: line.description or ""),
                )
                cases.append(
                    CorpusCase(
                        ordinal,
                        split,
                        family,
                        body,
                        "image/png" if family == "scan" else "application/pdf",
                        truth,
                        tuple(labels),
                        po_lines,
                        family in {"missing", "ambiguous"},
                        pdf.page_count,
                    )
                )
                pdf.close()
    return cases


def inventory(cases: list[CorpusCase], seed: int) -> dict[str, object]:
    records = [
        {
            "file": c.filename,
            "split": c.split,
            "family": c.family,
            "sha256": hashlib.sha256(c.body).hexdigest(),
            "truth": c.truth.model_dump(mode="json"),
            "labels": [label.model_dump(mode="json") for label in c.labels],
            "purchase_order_lines": [
                line.model_dump(mode="json") for line in c.purchase_order_lines
            ],
            "expected_review": c.expected_review,
            "pages": c.pages,
        }
        for c in cases
    ]
    fingerprint = hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()
    return {
        "corpus_version": CORPUS_VERSION,
        "seed": seed,
        "corpus_fingerprint": fingerprint,
        "records": records,
    }


def write_corpus(output: Path, repository: Path, seed: int) -> None:
    cases = generate_cases(seed)
    root = synthetic_scratch(output, repository, fresh=True)
    for case in cases:
        (root / case.filename).write_bytes(case.body)
    (root / "manifest.json").write_text(
        json.dumps(inventory(cases, seed), indent=2) + "\n",
        encoding="utf-8",
    )


def load_corpus(
    manifest: Path,
    repository: Path,
    partition: Literal["all", "development", "unseen"],
) -> tuple[list[CorpusCase], str, int]:
    _no_links(manifest.absolute())
    root = synthetic_scratch(manifest.parent, repository, fresh=False)
    try:
        raw = json.loads(manifest.read_bytes())
        seed = raw["seed"]
        if type(seed) is not int:
            raise ValueError("Invalid seed")
        cases = generate_cases(seed)
        expected = inventory(cases, seed)
        if raw != expected:
            raise ValueError("Inventory mismatch")
        for case in cases:
            path = root / case.filename
            _no_links(path)
            if path.read_bytes() != case.body:
                raise ValueError("Synthetic bytes mismatch")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError("Synthetic corpus verification failed; no upload permitted") from exc
    if partition not in {"all", "development", "unseen"}:
        raise ValueError("Invalid corpus partition")
    return (
        [c for c in cases if partition == "all" or c.split == partition],
        str(expected["corpus_fingerprint"]),
        seed,
    )


def synthetic_scratch(path: Path, repository: Path, *, fresh: bool) -> Path:
    _no_links(path.absolute())
    repository = repository.resolve()
    resolved = path.resolve()
    scratch = repository / "work" / "hybrid-live-synthetic"
    if not resolved.is_relative_to(scratch) or resolved == scratch:
        raise ValueError("Synthetic corpus must be in dedicated ignored scratch")
    relative = resolved.relative_to(repository).as_posix()
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", relative],
        cwd=repository,
        capture_output=True,
        check=False,
    )
    tracked = subprocess.check_output(
        ["git", "ls-files", "--", relative], cwd=repository, text=True
    )
    if ignored.returncode != 0 or tracked.strip():
        raise ValueError("Synthetic corpus must be ignored and untracked")
    if fresh:
        resolved.mkdir(parents=True, exist_ok=False)
    elif not resolved.is_dir():
        raise ValueError("Synthetic scratch directory does not exist")
    return resolved
