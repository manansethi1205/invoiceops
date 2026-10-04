from invoiceops.evaluation.supporting_documents import (
    fixed_specs,
    generate_bytes,
    run_generated_holdout,
)


def test_fixed_generated_split_and_real_document_bytes() -> None:
    specs = fixed_specs()
    assert len(specs) == 45
    assert sum(spec.split == "holdout" for spec in specs) == 30
    assert sum(spec.source == "image/png" and spec.split == "holdout" for spec in specs) == 6
    assert generate_bytes(specs[0]).startswith(b"\x89PNG")
    assert generate_bytes(specs[1]).startswith(b"%PDF")
    assert generate_bytes(specs[1]) == generate_bytes(specs[1])


def test_generated_holdout_reports_all_roles_and_missing_ocr() -> None:
    report = run_generated_holdout()
    assert report.holdout_documents == 30
    assert report.evaluated_documents + sum(report.failure_categories.values()) == 30
    assert report.schema_validity_on_all_holdout == report.evaluated_documents / 30
    assert report.comparison is not None
    assert set(report.comparison.deterministic) == {
        "PURCHASE_ORDER",
        "GOODS_RECEIPT",
        "DELIVERY_NOTE",
    }
    assert report.comparison.false_canonical_record_count == 0
    assert report.comparison.confirmation_rate is None
    serialized = report.model_dump_json()
    assert "Synthetic Supply Co" not in serialized
    assert "Custom steel part" not in serialized
    assert "C:\\Users" not in serialized
