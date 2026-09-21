# mypy: disable-error-code=import-untyped
import argparse
import json
from collections import Counter
from pathlib import Path

from invoiceops.evaluation.docile_sampling import DocileSamplingRecord, select_docile_sample

SEED = 1205


def _page_bucket(page_count: int) -> str:
    return "1" if page_count == 1 else "2" if page_count == 2 else "3+"


def _shot_bucket(cluster_size: int) -> str:
    return "zero" if cluster_size == 1 else "few" if cluster_size <= 4 else "many"


def build_records(dataset_path: Path) -> list[DocileSamplingRecord]:
    try:
        from docile.dataset import CachingConfig, Dataset
    except ImportError as exc:
        raise RuntimeError("Install the evaluation dependency group first") from exc
    dataset = Dataset("val", dataset_path, cache_images=CachingConfig.OFF)
    documents = list(dataset)
    cluster_counts = Counter(str(document.annotation.cluster_id) for document in documents)
    return [
        DocileSamplingRecord(
            document_id=str(document.docid),
            layout_cluster=str(document.annotation.cluster_id),
            page_bucket=_page_bucket(document.page_count),
            source=str(document.annotation.source),
            has_line_items=bool(document.annotation.li_fields),
            shot_bucket=_shot_bucket(cluster_counts[str(document.annotation.cluster_id)]),
        )
        for document in documents
    ]


def _manifest(document_ids: list[str]) -> dict[str, object]:
    return {
        "dataset": "docile",
        "source_split": "val",
        "seed": SEED,
        "document_ids": document_ids,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create fixed ID-only DocILE samples")
    parser.add_argument("--dataset-path", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/docile/manifests")
    )
    arguments = parser.parse_args()
    records = build_records(arguments.dataset_path)
    benchmark_ids = select_docile_sample(records, size=100, seed=SEED)
    smoke_records = [record for record in records if record.document_id in benchmark_ids]
    smoke_ids = select_docile_sample(smoke_records, size=10, seed=SEED)
    arguments.output_dir.mkdir(parents=True, exist_ok=True)
    for name, document_ids in (("smoke", smoke_ids), ("benchmark", benchmark_ids)):
        path = arguments.output_dir / f"{name}.json"
        path.write_text(
            json.dumps(_manifest(document_ids), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print("created deterministic 10-document smoke and 100-document benchmark ID manifests")


if __name__ == "__main__":
    main()
