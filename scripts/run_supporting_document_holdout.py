"""Write aggregate-only synthetic supporting-document holdout metrics."""

import argparse
from pathlib import Path

from invoiceops.evaluation.supporting_documents import write_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = write_report(args.output)
    print(
        f"{report.evaluated_documents}/{report.holdout_documents} evaluated; "
        f"failures={report.failure_categories}"
    )


if __name__ == "__main__":
    main()
