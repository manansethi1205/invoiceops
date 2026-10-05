"""Write aggregate-only synthetic supporting-document holdout metrics."""

import argparse
from pathlib import Path

from invoiceops.evaluation.supporting_documents import write_report, write_unseen_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--unseen", action="store_true")
    args = parser.parse_args()
    report = write_unseen_report(args.output) if args.unseen else write_report(args.output)
    print(
        f"{report.evaluated_documents}/{report.holdout_documents} evaluated; "
        f"failures={report.failure_categories}"
    )


if __name__ == "__main__":
    main()
