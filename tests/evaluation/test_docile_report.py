from invoiceops.evaluation.docile_report import (
    DocileAggregateReport,
    DocileModeMetrics,
    render_docile_markdown,
)


def _metrics(mode: str) -> DocileModeMetrics:
    return DocileModeMetrics(
        mode=mode,  # type: ignore[arg-type]
        document_count=10,
        supported_subset_kile_f1=0.5,
        supported_subset_lir_f1=0.4,
        official_full_kile_f1=0.2,
        official_full_lir_f1=0.1,
        official_full_kile_ap=0.15,
        official_full_lir_ap=0.05,
    )


def test_report_keeps_modes_and_metric_scopes_unambiguous() -> None:
    report = DocileAggregateReport(
        extractor_name="deterministic-baseline",
        extractor_version="0.2.0",
        sample_manifest_sha256="a" * 64,
        modes=[_metrics("end_to_end"), _metrics("precomputed_ocr")],
    )
    markdown = render_docile_markdown(report)

    assert "Supported-subset KILE F1" in markdown
    assert "Official full KILE F1" in markdown
    assert "End-to-end" in markdown
    assert "Precomputed OCR" in markdown
    assert "document_id" in markdown
    assert "C:\\" not in markdown
    assert "/data/docile" not in markdown
