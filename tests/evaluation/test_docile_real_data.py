import os
from pathlib import Path

import pytest

from invoiceops.evaluation.adapters.docile import DocileDatasetAdapter, DocileEvaluationMode

_DATASET_PATH = os.environ.get("DOCILE_DATASET_PATH")


@pytest.mark.docile
@pytest.mark.skipif(_DATASET_PATH is None, reason="DOCILE_DATASET_PATH is not configured")
@pytest.mark.parametrize("mode", list(DocileEvaluationMode))
def test_real_docile_smoke_extracts_both_modes(mode: DocileEvaluationMode) -> None:
    manifest = Path("data/docile/manifests/smoke.json")
    if not manifest.exists():
        pytest.fail("generate the frozen DocILE smoke manifest before running real-data tests")
    examples = DocileDatasetAdapter().load_examples(Path(str(_DATASET_PATH)), manifest, mode)
    assert len(examples) == 10
    for example in examples:
        DocileDatasetAdapter().extract(example)
