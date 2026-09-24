import argparse
from pathlib import Path

from invoiceops.matching.three_way_evaluation import run_evaluation, write_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run synthetic three-way matching evaluation")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evals/reports/matching/three-way-v1"),
    )
    args = parser.parse_args()
    write_report(args.output_dir, run_evaluation())
    print("wrote aggregate-only synthetic three-way matching report")


if __name__ == "__main__":
    main()
