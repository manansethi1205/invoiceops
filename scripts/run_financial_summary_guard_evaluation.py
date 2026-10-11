import argparse
from pathlib import Path

from invoiceops.evaluation.financial_summary_guard import run_pair


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline opt-in financial-summary guard comparison"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--private-diagnostics", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_pair(
            args.manifest,
            args.output_dir,
            args.private_diagnostics,
            repository=Path(__file__).resolve().parents[1],
        )
    except Exception:
        parser.exit(
            2, "Private paired evaluation refused; inspect inputs and fresh paths privately.\n"
        )
    print(f"Paired aggregate evaluation complete: {report.documents} documents; no provider calls.")


if __name__ == "__main__":
    main()
