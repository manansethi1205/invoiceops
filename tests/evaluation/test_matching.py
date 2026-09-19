from decimal import Decimal

from invoiceops.evaluation.matching import align_line_items
from invoiceops.evaluation.schemas import GroundTruthLineItem
from invoiceops.schemas.extraction import (
    BoundingBox,
    EvidenceSpan,
    ExtractedField,
    ExtractionStatus,
    InvoiceLine,
    TextSource,
)


def _field(value: object | None) -> ExtractedField[object]:
    return ExtractedField[object](
        value=value,
        status=ExtractionStatus.MISSING if value is None else ExtractionStatus.EXTRACTED,
        evidence=[]
        if value is None
        else [
            EvidenceSpan(
                page=0,
                bbox=BoundingBox(x0=0, y0=0, x1=0.1, y1=0.1),
                text="synthetic",
                source=TextSource.EMBEDDED,
            )
        ],
        rule_id=None if value is None else "test.synthetic.v1",
    )


def _line(description: str, total: str) -> InvoiceLine:
    return InvoiceLine(
        description=_field(description),
        quantity=_field(None),
        unit_price=_field(None),
        line_total=_field(Decimal(total)),
    )


def test_alignment_preserves_order_when_middle_prediction_is_missing() -> None:
    truth = [
        GroundTruthLineItem(description="A", line_total="10"),
        GroundTruthLineItem(description="B", line_total="20"),
        GroundTruthLineItem(description="C", line_total="30"),
    ]
    predictions = [_line("A", "10"), _line("C", "30")]

    pairs = align_line_items(truth, predictions)

    assert [(pair.ground_truth_index, pair.prediction_index) for pair in pairs] == [(0, 0), (2, 1)]
    assert all(pair.exact for pair in pairs)


def test_zero_score_items_are_not_forced_into_alignment() -> None:
    pairs = align_line_items(
        [GroundTruthLineItem(description="Expected", line_total="10")],
        [_line("Different", "99")],
    )
    assert pairs == []
