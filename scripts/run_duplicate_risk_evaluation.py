import argparse
from pathlib import Path

from invoiceops.risk.evaluation import (
    run_duplicate_risk_evaluation,
    write_duplicate_risk_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the synthetic duplicate-risk evaluation")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evals/reports/risk/duplicate-risk-v1"),
    )
    args = parser.parse_args()
    report = run_duplicate_risk_evaluation()
    write_duplicate_risk_report(args.output_dir, report)
    print("wrote aggregate-only synthetic duplicate-risk report")


if __name__ == "__main__":
    main()
