"""Offline, private failure attribution; no external SDK imports."""

import argparse
from pathlib import Path

from invoiceops.evaluation.failure_attribution import run_attribution


def main() -> None:
    parser = argparse.ArgumentParser(description="Private deterministic failure attribution")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--private-diagnostics", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_attribution(
            args.manifest,
            args.output_dir,
            args.private_diagnostics,
            repository=Path(__file__).resolve().parents[1],
        )
    except Exception:
        parser.exit(2, "Private attribution refused; inspect inputs and fresh paths privately.\n")
    print(
        f"Aggregate attribution complete: {report.attempted_documents} attempts; no provider calls."
    )


if __name__ == "__main__":
    main()
