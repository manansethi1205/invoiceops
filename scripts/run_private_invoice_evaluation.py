"""Human-labelled private baseline; deliberately no hybrid/provider imports or switches."""

import argparse
from pathlib import Path

from invoiceops.evaluation.real_input import run_private_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline private deterministic invoice benchmark")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--private-diagnostics", type=Path)
    parser.add_argument("--allow-holdout", action="store_true")
    args = parser.parse_args()
    try:
        report = run_private_benchmark(
            args.manifest,
            args.output_dir,
            repository=Path(__file__).resolve().parents[1],
            private_diagnostics=args.private_diagnostics,
            allow_holdout=args.allow_holdout,
        )
    except Exception:
        # Validation/decoder errors may contain labels, file names and private paths.
        parser.exit(
            2,
            "Private benchmark refused; inspect manifest, labels, runtime "
            "and fresh paths privately.\n",
        )
    print(
        f"Wrote aggregate-only deterministic report: {report.slices['all'].attempted_documents} "
        "attempts; no provider calls."
    )


if __name__ == "__main__":
    main()
