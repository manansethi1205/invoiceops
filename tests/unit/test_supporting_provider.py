from types import SimpleNamespace

from invoiceops.extraction.hybrid.schemas import RenderedPage
from invoiceops.extraction.supporting_hybrid import (
    DeliveryNoteCandidate,
    GoodsReceiptCandidate,
    PurchaseOrderCandidate,
)
from invoiceops.extraction.supporting_provider import OpenAISupportingVisionProvider
from invoiceops.schemas.cases import DocumentRole
from tests.unit.test_supporting_extraction import document_from_rows
from tests.unit.test_supporting_hybrid import field, po_candidate


def test_openai_adapter_uses_distinct_role_schemas_without_network() -> None:
    empty = field()
    receipt = GoodsReceiptCandidate(
        receipt_number=empty, referenced_po_number=empty,
        received_date=empty, supplier=empty, line_items=[],
    )
    candidates = {
        DocumentRole.PURCHASE_ORDER: po_candidate(),
        DocumentRole.GOODS_RECEIPT: receipt,
        DocumentRole.DELIVERY_NOTE: DeliveryNoteCandidate.model_validate(receipt.model_dump()),
    }
    seen: list[type[object]] = []

    class StubResponses:
        def parse(self, *, text_format, input, **kwargs):  # type: ignore[no-untyped-def]
            seen.append(text_format)
            assert kwargs["store"] is False
            assert kwargs["tools"] == []
            assert input[0]["role"] == "system"
            role = DocumentRole(input[1]["content"][0]["text"].removeprefix("Role: "))
            return SimpleNamespace(
                status="completed", output_parsed=candidates[role],
                usage=None, id="synthetic-response", model="fake-model",
            )

    provider = OpenAISupportingVisionProvider(
        api_key="synthetic-key", model="fake-model", timeout_seconds=1,
        image_detail="low", client=SimpleNamespace(responses=StubResponses()),
    )
    page = RenderedPage(page=0, mime_type="image/png", width=1, height=1, image_bytes=b"x")
    document = document_from_rows([[('Synthetic', .05)]])
    for role in candidates:
        provider.extract(role, [page], document)
    assert seen == [PurchaseOrderCandidate, GoodsReceiptCandidate, DeliveryNoteCandidate]
