from typing import Literal

from pydantic import BaseModel, ConfigDict


class FieldMapping(BaseModel):
    model_config = ConfigDict(frozen=True)

    task: Literal["KILE", "LIR"]
    docile_field_type: str
    invoiceops_field: str
    rationale: str


SUPPORTED_DOCILE_MAPPINGS = (
    FieldMapping(
        task="KILE",
        docile_field_type="document_id",
        invoiceops_field="invoice_number",
        rationale=(
            "DocILE's main document number is the invoice number inside InvoiceOps' "
            "invoice-only workflow; non-invoice documents remain a documented limitation."
        ),
    ),
    FieldMapping(
        task="KILE",
        docile_field_type="date_issue",
        invoiceops_field="invoice_date",
        rationale="Both fields represent the document issue date.",
    ),
    FieldMapping(
        task="KILE",
        docile_field_type="amount_total_net",
        invoiceops_field="subtotal",
        rationale="Both represent the document total before tax.",
    ),
    FieldMapping(
        task="KILE",
        docile_field_type="amount_total_tax",
        invoiceops_field="tax",
        rationale="Both represent the aggregate document tax amount.",
    ),
    FieldMapping(
        task="KILE",
        docile_field_type="amount_total_gross",
        invoiceops_field="total",
        rationale="Both represent the document total including tax.",
    ),
    FieldMapping(
        task="LIR",
        docile_field_type="line_item_description",
        invoiceops_field="description",
        rationale="Both represent the goods or services description for one line item.",
    ),
    FieldMapping(
        task="LIR",
        docile_field_type="line_item_quantity",
        invoiceops_field="quantity",
        rationale="Both represent the quantity for one line item.",
    ),
)

DOCILE_KILE_TO_INVOICEOPS = {
    mapping.docile_field_type: mapping.invoiceops_field
    for mapping in SUPPORTED_DOCILE_MAPPINGS
    if mapping.task == "KILE"
}
DOCILE_LIR_TO_INVOICEOPS = {
    mapping.docile_field_type: mapping.invoiceops_field
    for mapping in SUPPORTED_DOCILE_MAPPINGS
    if mapping.task == "LIR"
}

AMBIGUOUS_DOCILE_FIELDS = {
    "amount_due": "A payable balance can differ from the invoice gross total.",
    "currency_code_amount_due": (
        "A currency adjacent to amount due is not guaranteed to be the global invoice currency."
    ),
    "line_item_amount_gross": "InvoiceOps line_total does not encode gross-versus-net tax basis.",
    "line_item_amount_net": "InvoiceOps line_total does not encode gross-versus-net tax basis.",
    "line_item_unit_price_gross": (
        "InvoiceOps unit_price does not encode gross-versus-net tax basis."
    ),
    "line_item_unit_price_net": (
        "InvoiceOps unit_price does not encode gross-versus-net tax basis."
    ),
    "order_id": "An order number is not an invoice number.",
    "customer_order_id": "A customer order reference is not an invoice number.",
    "vendor_order_id": "A vendor order reference is not an invoice number.",
}
