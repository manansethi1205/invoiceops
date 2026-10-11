from collections import Counter
from dataclasses import replace

import pytest

from invoiceops.evaluation.hybrid_live import _hits, _po, _role_correct, mode_counts
from invoiceops.evaluation.hybrid_local import _fixture_candidate, _SyntheticScanTokens
from invoiceops.evaluation.live_corpus import CellLabel, generate_cases
from invoiceops.extraction.hybrid.fusion import fuse_invoice
from invoiceops.extraction.hybrid.router import route_extraction
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.matching.engine import match_invoice
from invoiceops.schemas.extraction import BoundingBox, EvidenceSpan, TextSource
from invoiceops.schemas.matching import MatchDecision


def test_label_plus_value_span_has_amount_role_without_center_inside_label() -> None:
    case = generate_cases(20261011)[0]
    label = CellLabel(
        role="subtotal",
        row=None,
        page=0,
        value="100.00",
        bbox=BoundingBox(x0=0.6, y0=0.1, x1=0.7, y1=0.12),
    )
    case = replace(case, labels=(label,))
    evidence = EvidenceSpan(
        page=0,
        text="Subtotal: 100.00",
        source=TextSource.EMBEDDED,
        bbox=BoundingBox(x0=0.25, y0=0.1, x1=0.71, y1=0.12),
    )
    assert (evidence.bbox.x0 + evidence.bbox.x1) / 2 < label.bbox.x0
    assert _hits([evidence], case.labels) == [label]
    assert _role_correct("subtotal", [evidence], case, None)


@pytest.mark.parametrize(
    "kind", ["competing-role", "wrong-role", "wrong-page", "edge-overlap", "wrong-row"]
)
def test_source_role_geometry_remains_conservative(kind: str) -> None:
    case = generate_cases(20261011)[0]
    labels = [
        CellLabel(
            role="subtotal",
            row=None,
            page=0,
            value="100.00",
            bbox=BoundingBox(x0=0.6, y0=0.1, x1=0.7, y1=0.12),
        )
    ]
    if kind == "competing-role":
        # Same printed amount, different financial role: values cannot resolve identity.
        labels.append(
            CellLabel(
                role="total",
                row=None,
                page=0,
                value="100.00",
                bbox=BoundingBox(x0=0.75, y0=0.1, x1=0.85, y1=0.12),
            )
        )
    if kind == "wrong-role":
        labels = [labels[0].model_copy(update={"role": "total"})]
    if kind == "wrong-row":
        labels = [labels[0].model_copy(update={"row": 1})]
    evidence = EvidenceSpan(
        page=1 if kind == "wrong-page" else 0,
        text="100.00",
        source=TextSource.EMBEDDED,
        bbox=BoundingBox(
            x0=0.699 if kind == "edge-overlap" else 0.25,
            x1=0.9 if kind in {"competing-role", "edge-overlap"} else 0.71,
            y0=0.1,
            y1=0.12,
        ),
    )
    assert not _role_correct("subtotal", [evidence], replace(case, labels=tuple(labels)), None)
    if kind == "competing-role":
        assert len(_hits([evidence], tuple(labels))) == 2


def test_matched_local_invoices_are_exact_and_role_scoring_is_not_row_precision() -> None:
    cases = generate_cases(20261011)
    text = _SyntheticScanTokens(cases)
    parser = DeterministicInvoiceExtractor()
    invoices = []
    matched_families: Counter[str] = Counter()
    for case in cases:
        document = text.extract(case.body, case.content_type)
        baseline = parser.extract(document)
        fusion = fuse_invoice(baseline, _fixture_candidate(case), document)
        invoice = fusion.invoice if route_extraction(baseline, document).invoke_vlm else baseline
        invoices.append(invoice)
        if match_invoice(invoice, _po(case)).decision == MatchDecision.MATCHED:
            matched_families[case.family] += 1
            counts = mode_counts([case], [invoice], [0])
            assert counts.line_tp == 2 and counts.line_fp == counts.line_fn == 0
            assert all(
                rate.numerator == rate.denominator == 1
                for rate in counts.header_exact_match.values()
            )
            assert not case.expected_review
            assert counts.expected_review_documents == 0
            assert counts.false_automatic_matches.numerator == 0

            # A broad amount span containing competing roles must STILL flag a MATCHED invoice.
            subtotal_label = next(
                label for label in case.labels if label.role == "subtotal" and label.row is None
            )
            total_label = next(
                label for label in case.labels if label.role == "total" and label.row is None
            )
            unsafe = invoice.model_copy(deep=True)
            unsafe.subtotal.evidence = [
                EvidenceSpan(
                    page=subtotal_label.page,
                    source=TextSource.EMBEDDED,
                    text="Subtotal and total",
                    bbox=BoundingBox(
                        x0=min(subtotal_label.bbox.x0, total_label.bbox.x0),
                        y0=min(subtotal_label.bbox.y0, total_label.bbox.y0),
                        x1=max(subtotal_label.bbox.x1, total_label.bbox.x1),
                        y1=max(subtotal_label.bbox.y1, total_label.bbox.y1),
                    ),
                )
            ]
            # Canonical values and the policy decision are unchanged; evaluation catches evidence.
            assert match_invoice(unsafe, _po(case)).decision == MatchDecision.MATCHED
            assert mode_counts([case], [unsafe], [0]).false_automatic_matches.numerator == 1
    assert matched_families == {"grid": 2, "roles": 2}
    combined = mode_counts(cases, invoices, [0] * len(cases))
    assert combined.false_automatic_matches.numerator == 0
    assert combined.false_automatic_matches.denominator == combined.expected_review_documents == 12
    assert combined.matched_documents == 4 and combined.review_documents == 12
