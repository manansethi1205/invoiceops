from invoiceops.evaluation.docile_sampling import DocileSamplingRecord, select_docile_sample


def test_docile_sample_ids_are_deterministic_and_stratified() -> None:
    records = [
        DocileSamplingRecord(
            document_id=f"doc-{index:03d}",
            layout_cluster=f"cluster-{index % 5}",
            page_bucket="1" if index % 2 else "2",
            source="ucsf" if index % 3 else "pif",
            has_line_items=index % 4 != 0,
            shot_bucket=("zero", "few", "many")[index % 3],
        )
        for index in range(120)
    ]

    first = select_docile_sample(records, size=100, seed=1205)
    second = select_docile_sample(records, size=100, seed=1205)

    assert first == second
    assert len(first) == len(set(first)) == 100
