from invoiceops.evaluation.docile_mapping import (
    AMBIGUOUS_DOCILE_FIELDS,
    DOCILE_KILE_TO_INVOICEOPS,
    DOCILE_LIR_TO_INVOICEOPS,
)


def test_only_semantically_supported_fields_are_mapped() -> None:
    assert DOCILE_KILE_TO_INVOICEOPS == {
        "document_id": "invoice_number",
        "date_issue": "invoice_date",
        "amount_total_net": "subtotal",
        "amount_total_tax": "tax",
        "amount_total_gross": "total",
    }
    assert DOCILE_LIR_TO_INVOICEOPS == {
        "line_item_description": "description",
        "line_item_quantity": "quantity",
    }


def test_ambiguous_amount_and_price_fields_are_rejected() -> None:
    assert "amount_due" in AMBIGUOUS_DOCILE_FIELDS
    assert "currency_code_amount_due" in AMBIGUOUS_DOCILE_FIELDS
    assert "line_item_amount_gross" in AMBIGUOUS_DOCILE_FIELDS
    assert "line_item_unit_price_net" in AMBIGUOUS_DOCILE_FIELDS
