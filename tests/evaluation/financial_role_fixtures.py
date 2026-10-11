"""Authored synthetic source roles, independent of extraction predictions."""

import json
from pathlib import Path
from typing import Any

import pymupdf


def challenge_fixture(
    chunks: list[tuple[float, float, str, str | None]], *, scan: bool = False
) -> tuple[bytes, dict[str, Any]]:
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((50, 50), "Synthetic contract invoice - not a real financial document")
    for x, y, text, _ in chunks:
        page.insert_text((x, y), text, fontsize=12)

    def field(text: str, x: float, y: float, *, money: bool) -> dict[str, Any]:
        rect = min(page.search_for(text), key=lambda r: abs(r.x0 - x) + abs(r.y1 - y))
        return dict(
            status="present",
            value=text.replace(",", "").replace(" ", "") if money else text,
            evidence=[
                dict(
                    page=0,
                    bbox=dict(
                        x0=rect.x0 / 600, x1=rect.x1 / 600, y0=rect.y0 / 800, y1=rect.y1 / 800
                    ),
                )
            ],
        )

    roles: dict[str, Any] = {}
    for index, (x, y, text, role) in enumerate(chunks):
        if role is None:
            continue
        # Authors mark the printed label, followed by its printed amount chunk.
        ax, ay, amount, _ = chunks[index + 1]
        record = dict(
            printed_label=field(text, x, y, money=False), amount=field(amount, ax, ay, money=True)
        )
        if role in ("component_tax", "unknown_or_ambiguous"):
            roles.setdefault(role, []).append(record)
        else:
            roles[role] = record
    label = dict(
        annotation_version="financial-roles-v1",
        provenance="synthetic_contract",
        labelled_without_predictions=True,
        invoice=dict(annotation_version="human-invoice-v1", provenance="human"),
        **roles,
    )
    body = page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("png") if scan else pdf.tobytes()
    pdf.close()
    return body, label


def write_contract_corpus(repository: Path, *, include_scan: bool = True) -> Path:
    # Role tags are authored facts about these printed fixtures, never parser output.
    fixtures = [
        [(50, 200, "Total", "gross_invoice_total"), (200, 200, "100.00", None)],
        [(50, 200, "Grand total", "gross_invoice_total"), (200, 200, "120.00", None)],
        [(50, 200, "Gross total", "gross_invoice_total"), (200, 200, "120.00", None)],
        [
            (50, 180, "Net", "net_subtotal"),
            (220, 200, "100.00", None),
            (330, 180, "Tax", "component_tax"),
            (330, 200, "20.00", None),
            (440, 180, "Gross", "gross_invoice_total"),
            (440, 200, "120.00", None),
            (50, 200, "Total", None),
        ],
        [
            (50, 200, "Total", "gross_invoice_total"),
            (200, 200, "100.00", None),
            (400, 200, "Reference", None),
            (510, 200, "7", None),
        ],
        [
            (50, 200, "Total", "gross_invoice_total"),
            (200, 200, "100.00", None),
            (50, 260, "Balance", "payable_balance"),
            (200, 260, "100.00", None),
        ],
        [(50, 200, "Total", "gross_invoice_total"), (50, 230, "100.00", None)],
        [(50, 200, "Total", "gross_invoice_total"), (200, 200, "1, 200.00", None)],
        [
            (50, 200, "Total Net", "net_subtotal"),
            (160, 200, "100.00", None),
            (280, 200, "Tax", "component_tax"),
            (320, 200, "20.00", None),
            (400, 200, "Payable", "payable_balance"),
            (465, 200, "80.00", None),
            (50, 260, "Gross amount", "gross_invoice_total"),
            (200, 260, "120.00", None),
        ],
        [(50, 200, "Amount", "unknown_or_ambiguous"), (200, 200, "100.00", None)],
        [
            (50, 200, "Amount due", "payable_balance"),
            (200, 200, "80.00", None),
            (50, 260, "Gross amount", "gross_invoice_total"),
            (200, 260, "120.00", None),
        ],
    ]
    root = repository / "work/real-invoice-private/financial-role-contract"
    root.mkdir(parents=True, exist_ok=False)
    records = []
    if include_scan:
        fixtures.append(fixtures[0])
    for index, chunks in enumerate(fixtures):
        scan = include_scan and index == len(fixtures) - 1
        body, labels = challenge_fixture(chunks, scan=scan)
        (root / f"source-{index}").write_bytes(body)
        (root / f"label-{index}.json").write_text(json.dumps(labels), encoding="utf-8")
        records.append(
            dict(
                document_id=f"contract-{index}",
                split="development",
                document_path=f"source-{index}",
                ground_truth_path=f"label-{index}.json",
                content_type="image/png" if scan else "application/pdf",
            )
        )
    manifest = root / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return manifest
