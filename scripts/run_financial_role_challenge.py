"""Network-free CLI; sanitized failures keep private manifest contents out of stdout."""

import argparse
from pathlib import Path

from invoiceops.evaluation.financial_role_challenge import run_challenge


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline printed financial-role challenge")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--private-diagnostics", type=Path, required=True)
    parser.add_argument("--observed-manifest", type=Path)
    parser.add_argument(
        "--cohort",
        choices=["observed_development", "new_authorized_challenge", "synthetic_contract"],
        required=True,
    )
    args = parser.parse_args()
    try:
        report = run_challenge(
            args.manifest,
            args.output_dir,
            args.private_diagnostics,
            repository=Path(__file__).resolve().parents[1],
            cohort=args.cohort,
            observed_manifest=args.observed_manifest,
        )
    except Exception:
        parser.exit(2, "Private challenge refused; inspect inputs and fresh paths privately.\n")
    print(f"Aggregate challenge complete: {report.documents} documents; no provider calls.")


if __name__ == "__main__":
    main()
