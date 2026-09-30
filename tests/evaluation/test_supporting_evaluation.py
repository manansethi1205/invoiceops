from invoiceops.cases.evaluation import run_supporting_evaluation


def test_supporting_evaluation_preserves_confirmation_safety_boundary() -> None:
    report = run_supporting_evaluation()

    assert report.document_count == 30
    assert report.system["false_canonical_record_count"] == 0
    assert report.system["confirmation_required_rate"] == 1.0
    assert report.purchase_order["schema_valid_rate"] == 1.0
    assert report.goods_receipt["schema_valid_rate"] == 1.0
