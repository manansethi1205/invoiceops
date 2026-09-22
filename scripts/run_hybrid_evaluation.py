import argparse
import json
from decimal import Decimal
from pathlib import Path

from invoiceops.config import get_settings
from invoiceops.evaluation.hybrid import (
    run_hybrid_live_manifest,
    run_hybrid_replay_evaluation,
    write_hybrid_report,
)
from invoiceops.extraction.hybrid.provider import OpenAIVisionExtractionProvider
from invoiceops.extraction.hybrid.renderer import PageRenderer


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic/hybrid invoice evaluation")
    parser.add_argument(
        "--mode",
        choices=("deterministic", "hybrid-replay", "hybrid-live"),
        default="hybrid-replay",
    )
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--allow-holdout", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("evals/reports/hybrid/0.3.0-replay")
    )
    parser.add_argument("--input-price-per-million", type=Decimal)
    parser.add_argument("--output-price-per-million", type=Decimal)
    args = parser.parse_args()
    if args.mode == "hybrid-live":
        if not args.allow_live:
            parser.error("hybrid-live requires --allow-live; replay is the safe default")
        if args.manifest is None:
            parser.error("hybrid-live requires --manifest")
        settings = get_settings()
        if not settings.vlm_enabled or settings.vlm_provider != "openai":
            parser.error("hybrid-live requires VLM_ENABLED=true and VLM_PROVIDER=openai")
        if settings.openai_api_key is None:
            parser.error("hybrid-live credentials are not configured")
        provider = OpenAIVisionExtractionProvider(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.vlm_model,
            timeout_seconds=settings.vlm_timeout_seconds,
            max_retries=settings.vlm_max_retries,
            image_detail=settings.vlm_image_detail,
        )
        report = run_hybrid_live_manifest(
            args.manifest,
            provider,
            PageRenderer(
                dpi=settings.vlm_render_dpi,
                max_dimension=settings.vlm_max_image_dimension,
                max_pages=settings.vlm_max_pages,
            ),
            allow_holdout=args.allow_holdout,
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
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
