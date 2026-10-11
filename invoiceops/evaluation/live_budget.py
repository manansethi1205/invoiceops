"""Evaluation-only admission bound; no changes to production provider defaults."""

import logging
import os
from datetime import date
from decimal import ROUND_CEILING, Decimal
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, ConfigDict

from invoiceops.extraction.hybrid.provider import (
    OpenAIVisionExtractionProvider,
    VisionProviderError,
)
from invoiceops.extraction.hybrid.schemas import (
    RenderedPage,
    VisionExtractionResponse,
    VisionUsage,
)
from invoiceops.schemas.extraction import DocumentText

PRICE_SNAPSHOT = "openai-standard-2026-10-11"
SUPPORTED_MODEL = "gpt-4.1-mini-2025-04-14"
MODEL_SOURCE = "https://developers.openai.com/api/docs/models/gpt-4.1-mini"
REQUEST_SOURCE = (
    "https://developers.openai.com/api/reference/python/resources/responses/methods/create"
)


def _logging_preflight() -> None:
    # The SDK's debug "Request options" log contains the image payload and source prompt.
    if os.environ.get("OPENAI_LOG") or any(
        logging.getLogger(name).isEnabledFor(logging.DEBUG)
        for name in ("openai", "openai._base_client", "httpx", "httpcore")
    ):
        raise ValueError("Verbose provider/HTTP logging is unsafe for this evaluation")


class PriceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    snapshot: str = PRICE_SNAPSHOT
    model: str = SUPPORTED_MODEL
    verified_on: date = date(2026, 10, 11)
    input_usd_per_million: Decimal = Decimal("0.40")
    output_usd_per_million: Decimal = Decimal("1.60")
    context_tokens: int = 1_047_576
    model_max_output_tokens: int = 32_768
    image_token_multiplier_bound: Decimal = Decimal("1.62")
    image_source: str = "https://developers.openai.com/api/docs/guides/images-vision"
    model_source: str = MODEL_SOURCE
    request_source: str = REQUEST_SOURCE


def verified_profile(model: str, snapshot: str, *, today: date | None = None) -> PriceProfile:
    profile = PriceProfile()
    age = ((today or date.today()) - profile.verified_on).days
    if model != profile.model or snapshot != profile.snapshot or not 0 <= age <= 7:
        raise ValueError("Model/pricing bounds are unsupported or stale; reverify before live use")
    return profile


class BudgetRefusal(VisionProviderError):
    code = "evaluation_budget_refused"


class SpendLedger:
    def __init__(self, profile: PriceProfile, limit: Decimal, max_output_tokens: int) -> None:
        if profile != PriceProfile():
            raise ValueError("Unverified price profile")
        if not limit.is_finite() or limit <= 0:
            raise ValueError("Spending limit must be finite and positive")
        if not 1 <= max_output_tokens <= profile.model_max_output_tokens:
            raise ValueError("Invalid maximum output tokens")
        self.profile = profile
        self.limit = limit
        self.max_output_tokens = max_output_tokens
        # Includes all image, prompt and schema tokens; never estimates image tokens locally.
        self.input_charge_bound = self.weighted_input(profile.context_tokens)
        self.request_bound = self.cost(self.input_charge_bound, max_output_tokens)
        if limit < self.request_bound:
            raise ValueError("Spending limit cannot reserve even one bounded request")
        self.accounted_upper = Decimal(0)
        self.known_cost = Decimal(0)
        self.calls = self.known_usage_calls = self.unknown_usage_calls = 0
        self.input_tokens = self.output_tokens = self.total_tokens = 0
        self.halted = False

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (
            Decimal(input_tokens) * self.profile.input_usd_per_million
            + Decimal(output_tokens) * self.profile.output_usd_per_million
        ) / Decimal(1_000_000)

    def weighted_input(self, tokens: int) -> int:
        return int(
            (Decimal(tokens) * self.profile.image_token_multiplier_bound).to_integral_value(
                rounding=ROUND_CEILING
            )
        )

    def reserve(self) -> None:
        if self.halted or self.accounted_upper + self.request_bound > self.limit:
            raise BudgetRefusal("No further request is authorized by the evaluation budget")
        self.accounted_upper += self.request_bound
        self.calls += 1

    def settle(self, usage: VisionUsage | None, *, verified_response: bool) -> None:
        if (
            not verified_response
            or usage is None
            or usage.input_tokens is None
            or usage.output_tokens is None
            or usage.total_tokens is None
            or usage.input_tokens > self.input_charge_bound
            or usage.output_tokens > self.max_output_tokens
            or usage.total_tokens != usage.input_tokens + usage.output_tokens
        ):
            # A timeout or invalid accounting may still have been billed. Keep the full bound.
            self.unknown_usage_calls += 1
            self.halted = True
            return
        cost = self.cost(usage.input_tokens, usage.output_tokens)
        # Retain a conservative image-weighting allowance even when usage is available.
        charged_bound = self.cost(
            min(self.input_charge_bound, self.weighted_input(usage.input_tokens)),
            usage.output_tokens,
        )
        self.accounted_upper += charged_bound - self.request_bound
        self.known_cost += cost
        self.known_usage_calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.total_tokens += usage.total_tokens


class _BoundedResponses:
    def __init__(self, responses: Any, ledger: SpendLedger) -> None:
        self.responses = responses
        self.ledger = ledger
        self.usage: VisionUsage | None = None
        self.verified = False

    def parse(self, **kwargs: Any) -> Any:
        response = self.responses.parse(
            **kwargs,
            max_output_tokens=self.ledger.max_output_tokens,
            service_tier="default",
            truncation="disabled",
        )
        raw = getattr(response, "usage", None)
        self.verified = (
            getattr(response, "model", None) == self.ledger.profile.model
            and getattr(response, "service_tier", None) == "default"
        )
        if raw is not None:
            if any(
                type(getattr(raw, name, None)) is not int
                for name in (
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                )
            ):
                self.verified = False
            try:
                self.usage = VisionUsage(
                    input_tokens=getattr(raw, "input_tokens", None),
                    output_tokens=getattr(raw, "output_tokens", None),
                    total_tokens=getattr(raw, "total_tokens", None),
                )
            except ValueError:
                self.verified = False
        if not self.verified:
            raise VisionProviderError("Provider returned unverified model or billing tier")
        return response


class BudgetedVisionProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        ledger: SpendLedger,
        timeout_seconds: float = 60,
        client: Any = None,
    ) -> None:
        self.ledger = ledger
        self.requested_model = ledger.profile.model
        self.fake = client is not None
        if client is None:
            _logging_preflight()
            verified_profile(ledger.profile.model, ledger.profile.snapshot)
            import httpx
            from openai import OpenAI

            _logging_preflight()

            # Pin the endpoint and disable proxies, redirects and SDK retries in this benchmark.
            client = OpenAI(
                api_key=api_key,
                base_url="https://api.openai.com/v1",
                max_retries=0,
                timeout=timeout_seconds,
                http_client=httpx.Client(
                    trust_env=False, follow_redirects=False, timeout=timeout_seconds
                ),
            )
        self._responses = _BoundedResponses(client.responses, ledger)
        self._client = client
        self._provider = OpenAIVisionExtractionProvider(
            api_key=api_key,
            model=self.requested_model,
            timeout_seconds=timeout_seconds,
            max_retries=0,
            image_detail="high",
            client=SimpleNamespace(responses=self._responses),
        )

    def extract(
        self, pages: list[RenderedPage], document: DocumentText
    ) -> VisionExtractionResponse:
        self.ledger.reserve()
        self._responses.usage = None
        self._responses.verified = False
        try:
            return self._provider.extract(pages, document)
        finally:
            self.ledger.settle(self._responses.usage, verified_response=self._responses.verified)

    def close(self) -> None:
        if not self.fake:
            self._client.close()
