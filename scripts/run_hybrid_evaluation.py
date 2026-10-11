import argparse
from decimal import Decimal
from pathlib import Path

from invoiceops.config import get_settings
from invoiceops.evaluation.hybrid import (
    run_hybrid_replay_evaluation,
    write_hybrid_report,
)
from invoiceops.evaluation.hybrid_live import output_preflight, run_hybrid_live_manifest
from invoiceops.evaluation.hybrid_local import run_hybrid_local_manifest
from invoiceops.evaluation.live_budget import (
    BudgetedVisionProvider,
    SpendLedger,
    verified_profile,
)
from invoiceops.evaluation.live_corpus import write_corpus
from invoiceops.extraction.hybrid.renderer import PageRenderer


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic/hybrid invoice evaluation")
    parser.add_argument(
        "--mode",
        choices=(
            "deterministic",
            "hybrid-replay",
            "hybrid-live",
            "synthetic-local",
            "generate-synthetic",
        ),
        default="hybrid-replay",
    )
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--allow-holdout", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--corpus-dir", type=Path)
    parser.add_argument("--seed", type=int, default=20261011)
    parser.add_argument("--model")
    parser.add_argument("--max-documents", type=int)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--max-spend-usd", type=Decimal)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--confirm-price-snapshot")
    parser.add_argument("--partition", choices=("all", "development", "unseen"), default="all")
    parser.add_argument("--local-source-mode", choices=("native", "synthetic-scan-tokens"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("evals/reports/hybrid/0.5.0-replay")
    )
    parser.add_argument("--input-price-per-million", type=Decimal)
    parser.add_argument("--output-price-per-million", type=Decimal)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    if args.local_source_mode is not None and args.mode != "synthetic-local":
        parser.error("--local-source-mode is permitted only for synthetic-local")
    if args.mode == "generate-synthetic":
        if args.corpus_dir is None:
            parser.error("generate-synthetic requires --corpus-dir in ignored scratch")
        try:
            write_corpus(args.corpus_dir, repository, args.seed)
        except (OSError, ValueError):
            parser.error(
                "Synthetic corpus generation refused; use a fresh ignored scratch directory"
            )
        print("generated 16 synthetic invoices with 32 labelled rows and 17 pages; no model called")
        return
    if args.mode == "synthetic-local":
        if args.allow_live or any(
            value is not None
            for value in (
                args.model,
                args.max_spend_usd,
                args.max_output_tokens,
                args.confirm_price_snapshot,
                args.input_price_per_million,
                args.output_price_per_million,
            )
        ):
            parser.error("synthetic-local refuses live authorization, model and billing options")
        if args.manifest is None or args.max_documents is None or args.max_pages is None:
            parser.error("synthetic-local requires manifest and explicit document/page limits")
        try:
            run_hybrid_local_manifest(
                args.manifest,
                max_documents=args.max_documents,
                max_pages=args.max_pages,
                output_dir=args.output_dir,
                repository=repository,
                partition=args.partition,
                allow_holdout=args.allow_holdout,
                source_mode=args.local_source_mode or "native",
            )
        except (OSError, ValueError, RuntimeError):
            parser.error(
                "Local synthetic benchmark refused; check corpus, runtime, limits and fresh output"
            )
        print("wrote synthetic-local aggregate report; no model, network, API tokens or cost")
        return
    if args.mode == "hybrid-live":
        if not args.allow_live:
            parser.error("hybrid-live requires --allow-live; replay is the safe default")
        if args.manifest is None:
            parser.error("hybrid-live requires --manifest")
        if any(
            value is None
            for value in (
                args.model,
                args.max_documents,
                args.max_pages,
                args.max_spend_usd,
                args.max_output_tokens,
                args.confirm_price_snapshot,
            )
        ):
            parser.error(
                "hybrid-live requires explicit model, document/page limits, spending limit, "
                "output-token bound and confirmed price snapshot"
            )
        if args.input_price_per_million is not None or args.output_price_per_million is not None:
            parser.error("live prices must come from the verified snapshot, not ad hoc estimates")
        try:
            profile = verified_profile(args.model, args.confirm_price_snapshot)
            ledger = SpendLedger(profile, args.max_spend_usd, args.max_output_tokens)
            output_preflight(args.output_dir, repository)
        except (OSError, ValueError):
            parser.error(
                "Live preflight refused: invalid/stale pricing, budget or output directory"
            )
        try:
            settings = get_settings()
            if settings.openai_api_key is None:
                parser.error("hybrid-live credentials are not configured")
            provider = BudgetedVisionProvider(
                api_key=settings.openai_api_key.get_secret_value(),
                ledger=ledger,
                timeout_seconds=settings.vlm_timeout_seconds,
            )
        except Exception:
            parser.error("Provider initialization refused; check credentials and logging privately")
        try:
            run_hybrid_live_manifest(
                args.manifest,
                provider,
                PageRenderer(max_pages=args.max_pages),
                allow_live=args.allow_live,
                max_documents=args.max_documents,
                max_pages=args.max_pages,
                output_dir=args.output_dir,
                repository=repository,
                partition=args.partition,
                allow_holdout=args.allow_holdout,
            )
        except (OSError, ValueError, RuntimeError):
            parser.error(
                "Live benchmark stopped; inspect runtime/preflight privately; "
                "no source or provider content is logged"
            )
        finally:
            provider.close()
        print("wrote aggregate-only explicitly enabled live hybrid report")
        return
    report = run_hybrid_replay_evaluation(
        input_price_per_million=args.input_price_per_million,
        output_price_per_million=args.output_price_per_million,
    )
    write_hybrid_report(args.output_dir, report)
    print("wrote aggregate-only hybrid replay report; no live provider call was made")


if __name__ == "__main__":
    main()
