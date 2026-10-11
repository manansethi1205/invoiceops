import argparse
from pathlib import Path

from invoiceops.evaluation.financial_role_versions import run_versions


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline three-version financial-role regression")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--private-diagnostics", type=Path, required=True)
    parser.add_argument(
        "--cohort", choices=["observed_development", "synthetic_contract"], required=True
    )
    args = parser.parse_args()
    try:
        report = run_versions(
            args.manifest,
            args.output_dir,
            args.private_diagnostics,
            repository=Path(__file__).resolve().parents[1],
            cohort=args.cohort,
        )
    except Exception:
        parser.exit(2, "Private comparison refused; inspect inputs and fresh paths privately.\n")
    print(f"Aggregate comparison complete: {report.documents} documents; no provider calls.")


if __name__ == "__main__":
    main()
