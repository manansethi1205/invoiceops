import argparse
from pathlib import Path

from invoiceops.cases.evaluation import run_supporting_evaluation, write_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evals/reports/cases/supporting-documents-v1"),
    )
    args = parser.parse_args()
    report = run_supporting_evaluation()
    if report.system["false_canonical_record_count"] != 0:
        raise SystemExit("false canonical record safety invariant failed")
    write_report(report, args.output_dir)
    print("wrote aggregate synthetic supporting-document report")


if __name__ == "__main__":
    main()
