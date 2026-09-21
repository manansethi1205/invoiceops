import argparse
from pathlib import Path

from invoiceops.matching.evaluation import run_matching_evaluation, write_matching_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run synthetic two-way matching evaluation")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evals/reports/matching/matching-v1"),
    )
    arguments = parser.parse_args()
    report = run_matching_evaluation()
    if report.false_auto_match_count != 0:
        raise RuntimeError("matching safety invariant failed: false auto-match count is non-zero")
    write_matching_report(arguments.output_dir, report)
    print("wrote aggregate-only deterministic matching report")


if __name__ == "__main__":
    main()
