import argparse
from pathlib import Path

from invoiceops.evaluation.reporting import write_outputs
from invoiceops.evaluation.runner import EvaluationRunner, HoldoutAccessError
from invoiceops.extraction.ocr_runtime import OcrRuntimeUnavailableError


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate InvoiceOps deterministic extraction")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--allow-holdout", action="store_true")
    arguments = parser.parse_args()
    try:
        report, results = EvaluationRunner().run(
            arguments.manifest, allow_holdout=arguments.allow_holdout
        )
    except (HoldoutAccessError, OcrRuntimeUnavailableError) as exc:
        parser.error(str(exc))
    write_outputs(arguments.output_dir, report, results)
    metrics = report["metrics"]
    assert isinstance(metrics, dict)
    documents = metrics["documents"]
    assert isinstance(documents, dict)
    print(
        f"evaluated {documents['attempted']} documents; "
        f"schema-valid={documents['schema_valid']}"
    )


if __name__ == "__main__":
    main()
