from decimal import Decimal

import pytest

from invoiceops.evaluation.row_alignment import SCENARIOS, fixture, run_stress, write_stress
from invoiceops.extraction.hybrid.fusion import fuse_invoice
from invoiceops.matching.engine import match_invoice
from invoiceops.schemas.extraction import ExtractedField, ExtractionStatus, Invoice
from invoiceops.schemas.matching import MatchDecision, ReasonCode


@pytest.mark.parametrize("kind", SCENARIOS)
def test_rows_never_mix_and_unresolved_cases_require_review(kind: str) -> None:
    invoice, candidate, document, po = fixture(kind)
    fused = fuse_invoice(invoice, candidate, document)
    assert fused.invoice.line_items == invoice.line_items
    result = match_invoice(fused.invoice, po)
    if fused.invoice.extraction_issues:
        assert result.decision == MatchDecision.NEEDS_REVIEW
        assert ReasonCode.EXTRACTION_ROW_ASSOCIATION_UNRESOLVED in result.reason_codes
    assert fuse_invoice(invoice, candidate, document) == fused
    assert Invoice.model_validate(fused.invoice.model_dump(mode="json")) == fused.invoice


@pytest.mark.parametrize("kind", ["ordered", "reordered", "wrapped", "ocr", "duplicate_amount"])
def test_unique_anchor_fills_only_its_own_missing_cell(kind: str) -> None:
    invoice, candidate, document, _ = fixture(kind)
    original = invoice.line_items[0].quantity
    invoice.line_items[0] = invoice.line_items[0].model_copy(
        update={
            "quantity": ExtractedField[Decimal](
                value=None, status=ExtractionStatus.MISSING, evidence=[]
            )
        }
    )
    fused = fuse_invoice(invoice, candidate, document)
    assert fused.invoice.line_items[0].quantity.value == original.value
    assert fused.invoice.line_items[0].quantity.evidence == original.evidence
    assert fused.invoice.line_items[1] == invoice.line_items[1]
    assert not fused.invoice.extraction_issues


def test_empty_model_rows_cannot_hide_complete_invoice_disagreement() -> None:
    invoice, candidate, document, po = fixture("no_candidates")
    assert match_invoice(invoice, po).decision == MatchDecision.MATCHED
    fused = fuse_invoice(invoice, candidate, document)
    assert match_invoice(fused.invoice, po).decision == MatchDecision.NEEDS_REVIEW


def test_stress_accounting_and_no_overwrite(tmp_path) -> None:
    report = run_stress()
    assert report["associated"] + report["abstained"] == report["candidate_rows"]
    assert report["cross_row_promotions"] == report["false_automatic_matches"] == 0
    assert report["association_precision"] == 1
    output = tmp_path / "fresh"
    write_stress(output)
    original = (output / "report.json").read_bytes()
    with pytest.raises(FileExistsError):
        write_stress(output)
    assert (output / "report.json").read_bytes() == original


def test_real_wrapped_tokens_and_multipage_anchors() -> None:
    invoice, candidate, document, _ = fixture("wrapped")
    original = document.pages[0].words[0]
    first = original.model_copy(
        update={
            "text": "Alpha",
            "bbox": original.bbox.model_copy(update={"y1": original.bbox.y0 + 0.02}),
        }
    )
    second = original.model_copy(
        update={
            "text": "wrapped",
            "line_number": 1,
            "bbox": original.bbox.model_copy(update={"y0": original.bbox.y0 + 0.025}),
        }
    )
    numeric = [
        w.model_copy(
            update={
                "bbox": w.bbox.model_copy(update={"y0": w.bbox.y0 + 0.025, "y1": w.bbox.y1 + 0.025})
            }
        )
        for w in document.pages[0].words[1:4]
    ]
    document.pages[0].words = [first, second] + numeric + document.pages[0].words[4:]
    fused = fuse_invoice(invoice, candidate, document)
    assert fused.row_associations == {0: 0, 1: 1}
    assert not fused.invoice.extraction_issues
    invoice, candidate, document, _ = fixture("multipage")
    fused = fuse_invoice(
        invoice, candidate.model_copy(update={"line_items": candidate.line_items[::-1]}), document
    )
    assert fused.row_associations == {0: 1, 1: 0}
    assert not fused.invoice.extraction_issues


def test_repeated_deterministic_anchor_and_zero_geometry_abstain() -> None:
    invoice, candidate, document, _ = fixture("ordered")
    invoice.line_items.append(invoice.line_items[0])
    fused = fuse_invoice(invoice, candidate, document)
    assert 0 not in fused.row_associations and 2 not in fused.row_associations
    assert fused.invoice.extraction_issues
    assert fused.invoice.line_items == invoice.line_items


@pytest.mark.parametrize("kind", SCENARIOS)
def test_partial_rows_never_promote_a_different_rows_quantity(kind: str) -> None:
    invoice, candidate, document, _ = fixture(kind)
    expected = [line.quantity.value for line in invoice.line_items]
    for index, line in enumerate(invoice.line_items):
        invoice.line_items[index] = line.model_copy(
            update={
                "quantity": ExtractedField[Decimal](
                    value=None, status=ExtractionStatus.MISSING, evidence=[]
                )
            }
        )
    fused = fuse_invoice(invoice, candidate, document)
    for index, line in enumerate(fused.invoice.line_items):
        assert line.quantity.value is None or line.quantity.value == expected[index]
        if line.quantity.status == ExtractionStatus.EXTRACTED:
            assert index in fused.row_associations


def test_tall_cell_cannot_touch_two_source_rows() -> None:
    invoice, candidate, document, _ = fixture("ordered")
    word = document.pages[0].words[3]
    document.pages[0].words[3] = word.model_copy(
        update={"bbox": word.bbox.model_copy(update={"y1": 0.38})}
    )
    fused = fuse_invoice(invoice, candidate, document)
    assert fused.grounding["candidate_rows.0"] == "incoherent_geometry"
    assert 0 not in fused.row_associations
    assert fused.invoice.line_items == invoice.line_items
    assert fused.invoice.extraction_issues


def test_additive_issue_contract_preserves_legacy_invoice_serialization() -> None:
    invoice, candidate, document, _ = fixture("no_candidates")
    legacy = invoice.model_dump(mode="json")
    assert "extraction_issues" not in legacy
    assert Invoice.model_validate(legacy).model_dump(mode="json") == legacy
    fused = fuse_invoice(invoice, candidate, document)
    assert fused.invoice.model_dump(mode="json")["extraction_issues"] == [
        "hybrid_row_association_unresolved"
    ]
