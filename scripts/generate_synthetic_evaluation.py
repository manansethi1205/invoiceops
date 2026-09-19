# mypy: disallow-untyped-calls=False
"""Generate the deterministic, synthetic InvoiceOps evaluation corpus."""

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pymupdf

SEED = 1205


@dataclass(frozen=True)
class Case:
    split: str
    family: str
    source: str
    ordinal: int


FAMILY_COUNTS = {
    "development": {
        "standard": 4,
        "aliases": 4,
        "missing_cells": 3,
        "wrapped": 3,
        "multipage": 3,
        "ocr": 3,
        "negative": 2,
        "adversarial": 3,
    },
    "holdout": {
        "standard": 2,
        "aliases": 2,
        "missing_cells": 2,
        "wrapped": 2,
        "multipage": 2,
        "ocr": 2,
        "negative": 1,
        "adversarial": 2,
    },
}


def _cases() -> list[Case]:
    cases: list[Case] = []
    for split, families in FAMILY_COUNTS.items():
        ordinal = 1
        for family, count in families.items():
            for _ in range(count):
                source = "ocr" if family == "ocr" else "digital"
                cases.append(Case(split, family, source, ordinal))
                ordinal += 1
    return cases


def _truth(case: Case) -> dict[str, object]:
    if case.family == "negative":
        return {"line_items": []}
    sequence = case.ordinal + (100 if case.split == "holdout" else 0)
    currency = ("INR", "USD", "EUR")[sequence % 3]
    first_quantity: str | None = "2"
    first_unit_price: str | None = "500.00"
    if case.family == "missing_cells":
        if sequence % 2:
            first_quantity = None
        else:
            first_unit_price = None
    return {
        "invoice_number": f"SYN-{sequence:05d}",
        "invoice_date": "2026-09-19",
        "currency": currency,
        "subtotal": "1200.00",
        "tax": "216.00",
        "total": "1416.00",
        "line_items": [
            {
                "description": "Industrial Filter Assembly"
                if case.family == "wrapped"
                else "Industrial Filter",
                "quantity": first_quantity,
                "unit_price": first_unit_price,
                "line_total": "1000.00",
            },
            {
                "description": "Mounting Bracket",
                "quantity": "4",
                "unit_price": "50.00",
                "line_total": "200.00",
            },
        ],
    }


def _insert_table(
    page: pymupdf.Page,
    truth: dict[str, object],
    *,
    start_y: float,
    wrapped: bool,
    only_item: int | None = None,
) -> None:
    columns = [(62, "Description"), (325, "Qty"), (395, "Unit Price"), (500, "Amount")]
    for x, label in columns:
        page.insert_text((x, start_y), label, fontsize=10)
    items = truth["line_items"]
    assert isinstance(items, list)
    selected = list(enumerate(items)) if only_item is None else [(only_item, items[only_item])]
    y = start_y + 32
    for index, item in selected:
        assert isinstance(item, dict)
        description = str(item["description"])
        if wrapped and index == 0:
            page.insert_text((62, y), "Industrial Filter", fontsize=10)
            y += 17
            description = "Assembly"
        values = [description, item.get("quantity"), item.get("unit_price"), item["line_total"]]
        for (x, _), value in zip(columns, values, strict=True):
            if value is not None:
                page.insert_text((x, y), str(value), fontsize=10)
        y += 30
    if only_item in (None, 1):
        page.insert_text((355, y + 12), "Subtotal: 1,200.00", fontsize=10)
        page.insert_text((355, y + 34), "GST: 216.00", fontsize=10)
        currency = str(truth["currency"])
        page.insert_text((355, y + 56), f"Grand Total: {currency} 1,416.00", fontsize=10)


def _digital_pdf(case: Case, truth: dict[str, object]) -> bytes:
    document = pymupdf.open()
    try:
        first = document.new_page(width=612, height=792)
        first.insert_text((62, 48), "SYNTHETIC DEMO DATA - NOT A REAL INVOICE", fontsize=10)
        if case.family == "negative":
            lines = [
                "Packing note for synthetic demonstration only",
                "This document intentionally contains no payable invoice fields",
                "Reference material without financial amounts or approval instructions",
            ]
            for index, line in enumerate(lines):
                first.insert_text((62, 100 + index * 24), line, fontsize=11)
            document.set_metadata({})
            return cast(bytes, document.tobytes(garbage=4, deflate=True, no_new_id=True))

        if case.family == "aliases":
            labels = (
                f"Bill No: {truth['invoice_number']}",
                "Issue Date: 19/09/2026",
                f"Currency: {truth['currency']}",
            )
        else:
            labels = (
                f"Invoice Number: {truth['invoice_number']}",
                "Invoice Date: 19/09/2026",
                f"Currency: {truth['currency']}",
            )
        for index, line in enumerate(labels):
            first.insert_text((62, 82 + index * 25), line, fontsize=11)
        if case.family == "adversarial":
            first.insert_text((320, 82), "PO Date: 18/09/2026", fontsize=10)
            first.insert_text((320, 107), "Quantity Total: 999.00", fontsize=10)
            first.insert_text((320, 132), "Discount Total: 0.00", fontsize=10)

        if case.family == "multipage":
            _insert_table(first, truth, start_y=220, wrapped=False, only_item=0)
            second = document.new_page(width=612, height=792)
            second.insert_text((62, 48), "SYNTHETIC DEMO DATA - PAGE 2", fontsize=10)
            _insert_table(second, truth, start_y=100, wrapped=False, only_item=1)
        else:
            _insert_table(
                first,
                truth,
                start_y=220 + (case.ordinal % 3) * 8,
                wrapped=case.family == "wrapped",
            )
        document.set_metadata({})
        return cast(bytes, document.tobytes(garbage=4, deflate=True, no_new_id=True))
    finally:
        document.close()


def _rasterize_pdf(body: bytes) -> bytes:
    source = pymupdf.open(stream=body, filetype="pdf")
    output = pymupdf.open()
    try:
        for page_number in range(source.page_count):
            source_page = source.load_page(page_number)
            pixmap = source_page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
            page = output.new_page(width=source_page.rect.width, height=source_page.rect.height)
            page.insert_image(page.rect, stream=pixmap.tobytes("png"))
        output.set_metadata({})
        return cast(bytes, output.tobytes(garbage=4, deflate=True, no_new_id=True))
    finally:
        output.close()
        source.close()


def generate(root: Path) -> None:
    documents = root / "documents"
    ground_truth = root / "ground_truth"
    manifests = root / "manifests"
    for directory in (documents, ground_truth, manifests):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
    records: dict[str, list[dict[str, object]]] = {"development": [], "holdout": []}
    for case in _cases():
        document_id = f"{case.split[:3]}-{case.ordinal:03d}"
        truth = _truth(case)
        pdf = _digital_pdf(case, truth)
        if case.source == "ocr":
            pdf = _rasterize_pdf(pdf)
        document_name = f"{document_id}.pdf"
        truth_name = f"{document_id}.json"
        (documents / document_name).write_bytes(pdf)
        (ground_truth / truth_name).write_text(
            json.dumps(truth, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        pages = "multiple" if case.family == "multipage" else "single"
        records[case.split].append(
            {
                "document_id": document_id,
                "split": case.split,
                "document_path": f"../documents/{document_name}",
                "content_type": "application/pdf",
                "ground_truth_path": f"../ground_truth/{truth_name}",
                "tags": {"layout": case.family, "pages": pages, "source": case.source},
            }
        )
    for split, entries in records.items():
        manifest = "dev.jsonl" if split == "development" else "holdout.jsonl"
        text = "\n".join(json.dumps(entry, sort_keys=True) for entry in entries) + "\n"
        (manifests / manifest).write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=Path("evals"))
    arguments = parser.parse_args()
    generate(arguments.output_root)
    print("generated 25 development and 15 holdout synthetic documents")


if __name__ == "__main__":
    main()
