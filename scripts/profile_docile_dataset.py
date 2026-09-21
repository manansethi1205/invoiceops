# mypy: disable-error-code=import-untyped
import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def profile_dataset(dataset_path: Path) -> dict[str, Any]:
    try:
        from docile.dataset import CachingConfig, Dataset
    except ImportError as exc:
        raise RuntimeError("Install the evaluation dependency group first") from exc
    dataset = Dataset("val", dataset_path, cache_images=CachingConfig.OFF)
    kile: Counter[str] = Counter()
    lir: Counter[str] = Counter()
    document_types: Counter[str] = Counter()
    page_counts: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    for document in dataset:
        annotation = document.annotation
        kile.update(field.fieldtype for field in annotation.fields if field.fieldtype)
        lir.update(field.fieldtype for field in annotation.li_fields if field.fieldtype)
        document_types[str(annotation.document_type)] += 1
        page_counts[str(document.page_count)] += 1
        sources[str(annotation.source)] += 1
    return {
        "documents": len(dataset),
        "kile_field_types": dict(sorted(kile.items())),
        "lir_field_types": dict(sorted(lir.items())),
        "document_types": dict(sorted(document_types.items())),
        "page_count_distribution": dict(sorted(page_counts.items(), key=lambda item: int(item[0]))),
        "sources": dict(sorted(sources.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Print aggregate-only DocILE validation counts")
    parser.add_argument("--dataset-path", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    payload = json.dumps(profile_dataset(arguments.dataset_path), indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
