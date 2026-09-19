import hashlib
from pathlib import Path

from invoiceops.evaluation.adapters.manifest import ManifestAdapter
from scripts.generate_synthetic_evaluation import generate


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_generator_is_deterministic_and_has_required_split_sizes(tmp_path: Path) -> None:
    root = tmp_path / "evals"
    generate(root)
    first = _hash_tree(root)
    assert len(ManifestAdapter().load(root / "manifests" / "dev.jsonl").examples) == 25
    holdout = ManifestAdapter().load(root / "manifests" / "holdout.jsonl")
    assert len(holdout.examples) == 15
    assert {example.tags["layout"] for example in holdout.examples} == {
        "standard",
        "aliases",
        "missing_cells",
        "wrapped",
        "multipage",
        "ocr",
        "negative",
        "adversarial",
    }

    generate(root)
    assert _hash_tree(root) == first
