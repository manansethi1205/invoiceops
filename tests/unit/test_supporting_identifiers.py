from invoiceops.evaluation.supporting_documents import fixed_specs, generate_bytes
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.extraction.supporting import (
    extract_goods_receipt,
    extract_goods_receipt_v1,
    extract_purchase_order,
    extract_purchase_order_v1,
)
from invoiceops.schemas.extraction import TextSource
from tests.unit.test_supporting_extraction import document_from_rows


def test_generated_pdf_po_and_receipt_identifiers_are_value_grounded() -> None:
    specs = fixed_specs()
    extractor = DocumentTextExtractor()
    po = extractor.extract(generate_bytes(specs[6]), "application/pdf")
    receipt = extractor.extract(generate_bytes(specs[21]), "application/pdf")
    delivery = extractor.extract(generate_bytes(specs[36]), "application/pdf")
    po_result = extract_purchase_order(po)
    receipt_result = extract_goods_receipt(receipt)
    assert po_result.po_number.value == "PO-106"
    assert po_result.po_number.evidence[0].text == "PO-106"
    assert extract_purchase_order_v1(po).po_number.status.value == "ambiguous"
    assert receipt_result.referenced_po_number.value == "PO-106"
    assert receipt_result.referenced_po_number.evidence[0].text == "PO-106"
    assert extract_goods_receipt_v1(receipt).referenced_po_number.status.value == "ambiguous"
    assert extract_goods_receipt(delivery).referenced_po_number.value == "PO-106"


def test_bare_identifier_is_not_a_label_and_adjacent_date_is_not_consumed() -> None:
    document = document_from_rows(
        [
            [("PO-106", 0.05)],
            [("Order", 0.05), ("Date:", 0.14), ("30/09/2026", 0.32)],
        ]
    )
    assert extract_purchase_order(document).po_number.value is None

    adjacent = document_from_rows(
        [
            [
                ("PO", 0.05),
                ("No:", 0.12),
                ("PO-106", 0.30),
                ("Order", 0.52),
                ("Date:", 0.62),
                ("30/09/2026", 0.78),
            ],
        ]
    )
    result = extract_purchase_order(adjacent)
    assert result.po_number.value == "PO-106"
    assert result.po_number.evidence[0].text == "PO-106"


def test_split_span_below_value_and_repeated_headers_agree() -> None:
    document = document_from_rows(
        [
            [("Purchase", 0.05), ("Order", 0.14), ("Number:", 0.24)],
            [("PO-106", 0.30)],
            [("PO:", 0.05), ("PO-106", 0.30)],
        ]
    )
    result = extract_purchase_order(document).po_number
    assert result.value == "PO-106"
    assert result.status.value == "extracted"
    assert len(result.evidence) == 2
    assert all(span.text == "PO-106" for span in result.evidence)


def test_conflicting_po_references_remain_ambiguous() -> None:
    document = document_from_rows(
        [
            [("Goods", 0.05), ("Receipt", 0.14), ("No:", 0.26), ("GR-1", 0.40)],
            [("PO", 0.05), ("No:", 0.12), ("PO-106", 0.30)],
            [("Purchase", 0.05), ("Order", 0.14), ("Number:", 0.24), ("PO-107", 0.40)],
        ]
    )
    result = extract_goods_receipt(document)
    assert result.receipt_number.value == "GR-1"
    assert result.referenced_po_number.value is None
    assert result.referenced_po_number.status.value == "ambiguous"
    assert {span.text for span in result.referenced_po_number.evidence} == {"PO-106", "PO-107"}


def test_ocr_tokens_use_the_same_geometry_and_do_not_cross_pages() -> None:
    document = document_from_rows(
        [
            [("PO", 0.05), ("No:", 0.12)],
            [("PO", 0.30), ("-", 0.35), ("106", 0.39)],
        ]
    )
    page = document.pages[0]
    document = document.model_copy(
        update={
            "pages": [
                page.model_copy(
                    update={
                        "source": TextSource.OCR,
                        "words": [
                            word.model_copy(update={"source": TextSource.OCR})
                            for word in page.words
                        ],
                    }
                )
            ],
            "used_ocr": True,
        }
    )
    result = extract_purchase_order(document).po_number
    assert result.value == "PO-106"
    assert result.evidence[0].source == TextSource.OCR

    second = document_from_rows([[("PO-106", 0.30)]]).pages[0]
    separate = document.model_copy(
        update={
            "pages": [
                page.model_copy(update={"words": page.words[:2]}),
                second.model_copy(
                    update={
                        "page": 1,
                        "words": [word.model_copy(update={"page": 1}) for word in second.words],
                    }
                ),
            ]
        }
    )
    assert extract_purchase_order(separate).po_number.value is None
