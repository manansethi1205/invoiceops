"""Network-free row association stress corpus; all content is synthetic."""

import json
import subprocess
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from invoiceops.extraction.hybrid.fusion import FusionResult, fuse_invoice
from invoiceops.extraction.hybrid.schemas import (
    CandidateField,
    CandidateLineItem,
    VisionInvoiceCandidate,
)
from invoiceops.extraction.version import HYBRID_EXTRACTOR_VERSION
from invoiceops.matching.engine import match_invoice
from invoiceops.schemas.extraction import (
    BoundingBox,
    DocumentText,
    EvidenceSpan,
    ExtractedField,
    ExtractionStatus,
    Invoice,
    InvoiceLine,
    OcrReason,
    PageText,
    TextSource,
    WordToken,
)
from invoiceops.schemas.matching import (
    MatchDecision,
    MatchingPolicy,
    PurchaseOrderLineRead,
    PurchaseOrderRead,
)

SCENARIOS = (
    "ordered",
    "reordered",
    "inserted",
    "deleted",
    "duplicate_candidate",
    "cross_row",
    "cross_page",
    "reused_cell",
    "duplicate_description",
    "duplicate_amount",
    "wrapped",
    "ocr",
    "missing_anchor",
    "no_candidates",
    "multipage",
)


def fixture(kind: str) -> tuple[Invoice, VisionInvoiceCandidate, DocumentText, PurchaseOrderRead]:
    source = TextSource.OCR if kind == "ocr" else TextSource.EMBEDDED
    texts = [["Alpha", "2", "5", "10"], ["Beta", "3", "7", "21"], ["Extra", "4", "8", "32"]]
    if kind == "duplicate_description":
        texts[1][0] = "Alpha"
    if kind == "duplicate_amount":
        texts[1][2] = "5"
        texts[1][3] = "15"
    if kind == "wrapped":
        texts[0][0] = "Alpha wrapped"
    words: list[WordToken] = []
    for row, cells in enumerate(texts):
        for column, text in enumerate(cells):
            words.append(
                WordToken(
                    text=text,
                    page=1 if kind in {"cross_page", "multipage"} and row == 1 else 0,
                    bbox=BoundingBox(
                        x0=column * 0.2,
                        x1=column * 0.2 + 0.15,
                        y0=0.2 + row * 0.15,
                        y1=0.22
                        + row * 0.15
                        + (0.025 if kind == "wrapped" and row == 0 and column == 0 else 0),
                    ),
                    block_number=0,
                    line_number=row,
                    word_number=column,
                    source=source,
                )
            )
    document = DocumentText(
        pages=[
            PageText(
                page=page,
                width=100,
                height=100,
                source=source,
                ocr_reason=OcrReason.NO_EMBEDDED_TEXT
                if source == TextSource.OCR
                else OcrReason.EMBEDDED_TEXT_SUFFICIENT,
                words=[w for w in words if w.page == page],
            )
            for page in sorted({w.page for w in words})
        ],
        used_ocr=source == TextSource.OCR,
    )

    def field(value: object, token: WordToken) -> ExtractedField[object]:
        return ExtractedField(
            value=value,
            status=ExtractionStatus.EXTRACTED,
            evidence=[
                EvidenceSpan(page=token.page, bbox=token.bbox, text=token.text, source=source)
            ],
        )

    lines = [
        InvoiceLine.model_validate(
            {
                name: field(
                    texts[row][column] if column == 0 else Decimal(texts[row][column]),
                    words[row * 4 + column],
                )
                for column, name in enumerate(
                    ("description", "quantity", "unit_price", "line_total")
                )
            }
        )
        for row in range(2)
    ]
    total = sum((line.line_total.value or Decimal(0) for line in lines), Decimal(0))
    invoice = Invoice.model_validate(
        dict(
            invoice_number=field("SYN-ROW", words[0]),
            invoice_date=field(date(2026, 1, 1), words[0]),
            currency=field("USD", words[0]),
            subtotal=field(total, words[0]),
            tax=field(Decimal(0), words[0]),
            total=field(total, words[0]),
            line_items=lines,
        )
    )
    missing = CandidateField(raw_value=None, page=None, evidence_quote=None)
    rows = [
        CandidateLineItem.model_validate(
            {
                name: CandidateField(
                    raw_value=texts[row][column],
                    page=words[row * 4].page,
                    evidence_quote=" ".join(texts[row]),
                )
                for column, name in enumerate(
                    ("description", "quantity", "unit_price", "line_total")
                )
            }
        )
        for row in range(3)
    ]
    selected = rows[:2]
    if kind == "reordered":
        selected = selected[::-1]
    if kind == "inserted":
        selected = [rows[2], rows[0], rows[1]]
    if kind == "deleted":
        selected = [rows[1]]
    if kind == "duplicate_candidate":
        selected = [rows[0], rows[0], rows[1]]
    if kind in {"cross_row", "cross_page"}:
        selected = [rows[0].model_copy(update={"line_total": rows[1].line_total}), rows[1]]
    if kind == "reused_cell":
        selected = [rows[0].model_copy(update={"quantity": rows[0].unit_price}), rows[1]]
    if kind == "missing_anchor":
        selected = [rows[0].model_copy(update={"description": missing}), rows[1]]
    if kind == "no_candidates":
        selected = []
    candidate = VisionInvoiceCandidate(
        invoice_number=missing,
        invoice_date=missing,
        currency=missing,
        subtotal=missing,
        tax=missing,
        total=missing,
        line_items=selected,
    )
    po_id = uuid.UUID(int=1)
    po = PurchaseOrderRead(
        id=po_id,
        external_po_number="SYN-ROW",
        vendor_name=None,
        currency="USD",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        lines=[
            PurchaseOrderLineRead(
                id=uuid.UUID(int=i + 2),
                purchase_order_id=po_id,
                line_number=str(i + 1),
                description=line.description.value or "",
                ordered_quantity=line.quantity.value or Decimal(0),
                unit_price=line.unit_price.value or Decimal(0),
                line_total=line.line_total.value,
            )
            for i, line in enumerate(lines)
        ],
    )
    return invoice, candidate, document, po


def run_stress() -> dict[str, object]:
    associated = attempted = abstained = reviews = false_auto = cross_row = correct = unresolved = 0
    filled = promoted_correct = 0
    for kind in SCENARIOS:
        invoice, candidate, document, po = fixture(kind)
        fused: FusionResult = fuse_invoice(invoice, candidate, document)
        reasons = [
            value
            for key, value in fused.grounding.items()
            if key.startswith("candidate_rows.") and key.count(".") == 1
        ]
        expected = {i: i for i in range(2)}
        if kind == "reordered":
            expected = {0: 1, 1: 0}
        elif kind == "inserted":
            expected = {0: 1, 1: 2}
        elif kind == "deleted":
            expected = {1: 0}
        elif kind == "duplicate_candidate":
            expected = {1: 2}
        elif kind in {"cross_row", "cross_page", "reused_cell", "missing_anchor"}:
            expected = {1: 1}
        elif kind == "no_candidates":
            expected = {}
        correct += sum(expected.get(d) == c for d, c in fused.row_associations.items())
        associated += reasons.count("associated")
        attempted += len(reasons)
        abstained += len(reasons) - reasons.count("associated")
        cross_row += int(fused.invoice.line_items != invoice.line_items)
        partial = invoice.model_copy(
            update={
                "line_items": [
                    line.model_copy(
                        update={
                            "quantity": ExtractedField[Decimal](
                                value=None, status=ExtractionStatus.MISSING, evidence=[]
                            )
                        }
                    )
                    for line in invoice.line_items
                ]
            }
        )
        promoted = fuse_invoice(partial, candidate, document)
        for index, line in enumerate(promoted.invoice.line_items):
            if line.quantity.status == ExtractionStatus.EXTRACTED:
                filled += 1
                valid = line.quantity.value == invoice.line_items[index].quantity.value
                promoted_correct += valid
                cross_row += not valid
        decision = match_invoice(fused.invoice, po).decision
        reviews += decision == MatchDecision.NEEDS_REVIEW
        unresolved += bool(fused.invoice.extraction_issues)
        requires_review = kind in {
            "inserted",
            "deleted",
            "duplicate_candidate",
            "cross_row",
            "cross_page",
            "reused_cell",
            "missing_anchor",
            "no_candidates",
            "duplicate_description",
        }
        false_auto += requires_review and decision == MatchDecision.MATCHED
    return dict(
        dataset="synthetic-row-alignment-v1",
        extractor_version=HYBRID_EXTRACTOR_VERSION,
        schema_version="invoice-v2",
        matching_policy=MatchingPolicy().version,
        source_revision=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        source_state=(
            "uncommitted working tree implementation"
            if subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
            else "committed revision"
        ),
        cases=len(SCENARIOS),
        candidate_rows=attempted,
        missing_quantity_cells=2 * len(SCENARIOS),
        promoted_quantity_cells=filled,
        correct_quantity_promotions=promoted_correct,
        associated=associated,
        abstained=abstained,
        correct_associations=correct,
        association_precision=correct / associated if associated else 0.0,
        association_coverage=associated / attempted,
        review_cases=reviews,
        unresolved_invoices=unresolved,
        expected_review_cases=9,
        false_automatic_matches=false_auto,
        cross_row_promotions=cross_row,
        limitations=[
            "Synthetic observed development corpus; not a population estimate.",
            "No live models. Candidate-only rows always abstain.",
            "Geometry gate uses normalized pages and bounded descriptions.",
        ],
    )


def write_stress(output: Path) -> None:
    report = run_stress()
    output.mkdir(parents=True, exist_ok=False)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output / "report.md").write_text(
        "# Row association stress evaluation\n\n"
        + "\n".join(f"- {key}: {value}" for key, value in report.items())
        + "\n",
        encoding="utf-8",
    )
