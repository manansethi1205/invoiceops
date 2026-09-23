import argparse
from pathlib import Path

from invoiceops.review.evaluation import run_review_evaluation, write_review_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run synthetic review-workflow evaluation")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("evals/reports/review/review-v1"),
    )
    arguments = parser.parse_args()
    report = run_review_evaluation()
    invariants = {
        "duplicate_case_count": report.duplicate_case_count == 0,
        "event_chain_verification_rate": report.event_chain_verification_rate == 1,
        "state_reconstruction_accuracy": report.state_reconstruction_accuracy == 1,
        "unauthorized_owner_action_rejection_rate": (
            report.unauthorized_owner_action_rejection_rate == 1
        ),
        "false_auto_resolution_count": report.false_auto_resolution_count == 0,
    }
    failed = [name for name, passed in invariants.items() if not passed]
    if failed:
        raise RuntimeError(f"review safety invariants failed: {', '.join(failed)}")
    write_review_report(arguments.output_dir, report)
    print("wrote aggregate-only synthetic review workflow report")


if __name__ == "__main__":
    main()
