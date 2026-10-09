from decimal import Decimal

import pytest

from invoiceops.extraction.hybrid.router import route_extraction
from invoiceops.extraction.hybrid.schemas import RoutingReason
from invoiceops.extraction.line_coverage_candidate import (
    LineCoverageInvoiceExtractor,
    TwoColumnHeader,
    detect_candidate_header,
    extract_candidate_line_items,
)
from invoiceops.extraction.line_item_rules import extract_line_items
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.table_layout import reconstruct_visual_rows
from invoiceops.extraction.version import CURRENT_EXTRACTION_STRATEGIES
from invoiceops.matching.engine import match_invoice
from invoiceops.schemas.extraction import ExtractionStatus, TextSource
from invoiceops.schemas.matching import MatchDecision, ReasonCode
from tests.matching.helpers import invoice, purchase_order
from tests.unit.test_line_item_rules import document, table_page


def two_column_page(rows, *, page=0, source=TextSource.EMBEDDED, labels=("Description", "Amount")):
    return table_page(page, rows, source=source, aliases=(labels[0], "", "", labels[1]))


@pytest.mark.parametrize("source", [TextSource.EMBEDDED, TextSource.OCR])
@pytest.mark.parametrize("labels", [("Description", "Amount"), ("Particulars", "Net Amount")])
def test_explicit_two_column_table_emits_only_observed_fields(source, labels) -> None:
    doc = document(
        two_column_page(
            [(0.25, "Synthetic Part", "", "", "USD 20.00")], source=source, labels=labels
        )
    )
    assert extract_line_items(doc) == []
    items = extract_candidate_line_items(doc)
    assert len(items) == 1
    assert items[0].description.value == "Synthetic Part"
    assert items[0].line_total.value == Decimal("20")
    for field in (items[0].quantity, items[0].unit_price):
        assert field.status == ExtractionStatus.MISSING
        assert field.value is None and field.evidence == []
    description, total = items[0].description.evidence[0], items[0].line_total.evidence[0]
    assert description.bbox.x0 == 0.08 and description.bbox.x1 < 0.5
    assert total.bbox.x0 == 0.84 and total.bbox.y0 == 0.25
    assert total.bbox.y1 == 0.27 and total.text == "USD 20.00"
    assert description.source == total.source == source


@pytest.mark.parametrize(
    "labels",
    [
        ("Description", "Total"),  # No bare-total alias expansion.
        ("Description Price", "Amount"),  # No new unit-price alias.
        ("Please review Description", "Amount"),  # Prose containing label words.
        ("Description Item", "Amount"),  # Competing description anchors.
        ("Description", "Amount Value"),  # Competing money anchors.
        ("Description", ""),  # No printed amount header.
        ("Tax", "Amount"),  # A tax summary is not an item table.
    ],
)
def test_unsupported_or_ambiguous_header_does_not_open_two_column_mode(labels) -> None:
    doc = document(two_column_page([(0.25, "Synthetic Part", "", "", "20.00")], labels=labels))
    assert extract_candidate_line_items(doc) == []


def test_unseparated_inline_prose_labels_are_not_a_header() -> None:
    from tests.unit.test_line_item_rules import cell_words

    page = two_column_page([])
    page.words = cell_words(
        "Description Amount", page=0, x0=0.08, y0=0.2, block=0, source=TextSource.EMBEDDED
    )
    assert detect_candidate_header(reconstruct_visual_rows(document(page))[0]) is None


def test_frozen_three_column_and_four_column_tables_are_identical() -> None:
    for labels in [
        ("Description", "Qty", "Unit Price", "Amount"),
        ("Description", "Qty", "", "Amount"),
    ]:
        doc = document(
            table_page(
                0,
                [
                    (0.25, "Synthetic Part", "2", "10.00" if labels[2] else "", "20.00"),
                    (0.29, "wrapped description", "", "", ""),
                    (0.35, "Grand Total", "", "", "20.00"),
                ],
                aliases=labels,
            )
        )
        assert extract_candidate_line_items(doc) == extract_line_items(doc)


def test_repeated_headers_same_page_and_multipage_are_isolated() -> None:
    first = two_column_page([(0.25, "First Part", "", "", "10.00")])
    repeated = two_column_page([(0.25, "Second Part", "", "", "20.00")])
    for word in repeated.words:
        first.words.append(
            word.model_copy(
                update={
                    "bbox": word.bbox.model_copy(
                        update={
                            "y0": word.bbox.y0 + 0.25,
                            "y1": word.bbox.y1 + 0.25,
                        }
                    ),
                }
            )
        )
    second = two_column_page([(0.25, "Third Part", "", "", "30.00")], page=1, source=TextSource.OCR)
    items = extract_candidate_line_items(document(first, second))
    assert [item.description.value for item in items] == ["First Part", "Second Part", "Third Part"]
    assert [item.description.evidence[0].page for item in items] == [0, 0, 1]
    assert items[-1].description.evidence[0].source == TextSource.OCR


def test_close_wrapping_has_bounded_evidence_and_distant_prose_is_not_joined() -> None:
    doc = document(
        two_column_page(
            [
                (0.25, "Synthetic Part", "", "", "20.00"),
                (0.28, "with coating", "", "", ""),
                (0.45, "This is general prose", "", "", ""),
            ]
        )
    )
    item = extract_candidate_line_items(doc)[0]
    assert item.description.value == "Synthetic Part with coating"
    assert item.description.evidence[0].bbox.y0 == 0.25
    assert item.description.evidence[0].bbox.y1 == pytest.approx(0.30)


def test_equidistant_wrap_does_not_guess_a_target() -> None:
    doc = document(
        two_column_page(
            [
                (0.25, "First Part", "", "", "20.00"),
                (0.29, "uncertain phrase", "", "", ""),
                (0.33, "Second Part", "", "", "30.00"),
            ]
        )
    )
    assert [item.description.value for item in extract_candidate_line_items(doc)] == [
        "First Part",
        "Second Part",
    ]


def test_cross_page_description_continuation_is_not_joined() -> None:
    first = two_column_page([(0.25, "Synthetic Part", "", "", "20.00")])
    second = table_page(1, [(0.25, "cross page phrase", "", "", "")], aliases=("", "", "", ""))
    item = extract_candidate_line_items(document(first, second))[0]
    assert item.description.value == "Synthetic Part"
    assert {span.page for span in item.description.evidence} == {0}


@pytest.mark.parametrize(
    "footer",
    [
        "Subtotal",
        "Grand Total",
        "Total",
        "Terms and Conditions",
        "Bank Details",
        "Thank you for your business",
        "Please remit payment",
    ],
)
def test_footer_and_prose_terminate_new_two_column_section(footer) -> None:
    doc = document(
        two_column_page(
            [
                (0.25, "Synthetic Part", "", "", "20.00"),
                (0.30, footer, "", "", "20.00"),
                (0.35, "Not a table item after footer", "", "", "900.00"),
            ]
        )
    )
    assert [item.description.value for item in extract_candidate_line_items(doc)] == [
        "Synthetic Part"
    ]


@pytest.mark.parametrize("amount", ["", "not printed", "20.00 30.00", "2 USD 20.00"])
def test_missing_invalid_or_multiple_numeric_values_are_not_inferred(amount) -> None:
    doc = document(two_column_page([(0.25, "Synthetic Part", "", "", amount)]))
    assert extract_candidate_line_items(doc) == []


def test_footer_prefix_inside_a_real_description_is_preserved() -> None:
    doc = document(
        two_column_page(
            [
                (0.25, "Tax Consulting Service", "", "", "20.00"),
                (0.30, "Total Replacement Kit", "", "", "30.00"),
            ]
        )
    )
    assert [item.description.value for item in extract_candidate_line_items(doc)] == [
        "Tax Consulting Service",
        "Total Replacement Kit",
    ]


def test_incomplete_candidate_remains_reviewable_and_routes_without_a_model_call() -> None:
    doc = document(two_column_page([(0.25, "Synthetic Part", "", "", "20.00")]))
    lines = extract_candidate_line_items(doc)
    extracted = invoice(subtotal="20", tax="0", total="20").model_copy(update={"line_items": lines})
    result = match_invoice(extracted, purchase_order(lines=[("1", "Synthetic Part", "2", "10")]))
    assert result.decision == MatchDecision.NEEDS_REVIEW
    assert ReasonCode.INVOICE_SCHEMA_INCOMPLETE in result.reason_codes
    decision = route_extraction(extracted, doc)
    assert RoutingReason.INCOMPLETE_LINE_ITEMS in decision.reasons
    assert lines[0].quantity.status == lines[0].unit_price.status == ExtractionStatus.MISSING


def test_candidate_is_separately_versioned_and_not_selected_for_production() -> None:
    candidate = LineCoverageInvoiceExtractor()
    assert (candidate.name, candidate.version) not in CURRENT_EXTRACTION_STRATEGIES
    assert (DeterministicInvoiceExtractor.name, DeterministicInvoiceExtractor.version) == (
        "deterministic-baseline",
        "0.2.0",
    )
    doc = document(two_column_page([(0.25, "Synthetic Part", "", "", "20.00")]))
    before, after = DeterministicInvoiceExtractor().extract(doc), candidate.extract(doc)
    for field in ("invoice_number", "invoice_date", "currency", "subtotal", "tax", "total"):
        assert getattr(before, field) == getattr(after, field)
    assert isinstance(detect_candidate_header(reconstruct_visual_rows(doc)[0]), TwoColumnHeader)


def test_two_column_like_text_does_not_replace_an_active_frozen_table() -> None:
    doc = document(
        table_page(
            0,
            [
                (0.25, "Synthetic Part", "2", "10.00", "20.00"),
                (0.30, "Description", "", "", "Amount"),
                (0.35, "Second Part", "1", "30.00", "30.00"),
            ],
        )
    )
    assert extract_candidate_line_items(doc) == extract_line_items(doc)
