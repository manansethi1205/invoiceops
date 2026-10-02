"""Write aggregate-only supporting replay metrics; never export tokens or predictions."""

import argparse
from decimal import Decimal
from pathlib import Path

from invoiceops.evaluation.supporting_hybrid import run_supporting_replay_evaluation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input-cost-per-million", type=Decimal)
    parser.add_argument("--output-cost-per-million", type=Decimal)
    args = parser.parse_args()
    if (args.input_cost_per_million is None) != (args.output_cost_per_million is None):
        parser.error("both input and output token prices are required for a cost estimate")
    if any(
        price is not None and price < 0
        for price in (args.input_cost_per_million, args.output_cost_per_million)
    ):
        parser.error("token prices must be nonnegative")
    report = run_supporting_replay_evaluation(
        input_cost_per_million=args.input_cost_per_million,
        output_cost_per_million=args.output_cost_per_million,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print("wrote aggregate-only synthetic supporting replay report")


if __name__ == "__main__":
    main()
