import base64
import hashlib
import json
import logging
import socket
import subprocess
import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from invoiceops.evaluation.hybrid_live import (
    LiveReport,
    _combine,
    audit_fusion,
    mode_counts,
    output_preflight,
    run_hybrid_live_manifest,
)
from invoiceops.evaluation.live_budget import (
    PRICE_SNAPSHOT,
    SUPPORTED_MODEL,
    BudgetedVisionProvider,
    BudgetRefusal,
    PriceProfile,
    SpendLedger,
    verified_profile,
)
from invoiceops.evaluation.live_corpus import (
    FAMILIES,
    CorpusCase,
    generate_cases,
    inventory,
    load_corpus,
    write_corpus,
)
from invoiceops.extraction.hybrid.fusion import HEADER_FIELDS, LINE_FIELDS, fuse_invoice
from invoiceops.extraction.hybrid.provider import VisionProviderError
from invoiceops.extraction.hybrid.renderer import PageRenderer
from invoiceops.extraction.hybrid.schemas import CandidateField, VisionInvoiceCandidate
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.schemas.extraction import (
    BoundingBox,
    DocumentText,
    EvidenceSpan,
    ExtractionStatus,
    Invoice,
    OcrReason,
    PageText,
    TextSource,
    WordToken,
)


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Network access is forbidden in benchmark tests")

    monkeypatch.setattr(socket.socket, "connect", refused)


@pytest.fixture(scope="module")
def cases() -> list[CorpusCase]:
    return generate_cases(20261011)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("work/\n", encoding="utf-8")
    return tmp_path


def missing() -> CandidateField:
    return CandidateField(raw_value=None, page=None, evidence_quote=None)


def candidate(case: CorpusCase) -> VisionInvoiceCandidate:
    values: dict[str, Any] = {}
    for name in HEADER_FIELDS:
        label = next(label for label in case.labels if label.role == name)
        prefix = {"subtotal": "Subtotal: ", "tax": "Tax: ", "total": "Total: "}.get(name, "")
        values[name] = CandidateField(
            raw_value=label.value, page=label.page, evidence_quote=prefix + label.value
        )
    rows: list[dict[str, CandidateField]] = []
    for row in range(2):
        labels = [label for label in case.labels if label.row == row]
        quote = " ".join(label.value for label in sorted(labels, key=lambda label: label.bbox.x0))
        cells = {}
        for name in LINE_FIELDS:
            label = next((label for label in labels if label.role == name), None)
            cells[name] = (
                CandidateField(raw_value=label.value, page=label.page, evidence_quote=quote)
                if label
                else missing()
            )
        rows.append(cells)
    return VisionInvoiceCandidate.model_validate({**values, "line_items": rows})


def labelled_baseline(case: CorpusCase) -> Invoice:
    def field(name: str, row: int | None) -> dict[str, Any]:
        label = next(
            (label for label in case.labels if label.role == name and label.row == row), None
        )
        value = (
            getattr(case.truth, name) if row is None else getattr(case.truth.line_items[row], name)
        )
        return {
            "value": value,
            "status": "extracted" if value is not None else "missing",
            "evidence": [
                EvidenceSpan(
                    page=label.page, bbox=label.bbox, text=label.value, source=TextSource.EMBEDDED
                )
            ]
            if label and value is not None
            else [],
        }

    return Invoice.model_validate(
        {
            **{name: field(name, None) for name in HEADER_FIELDS},
            "line_items": [{name: field(name, row) for name in LINE_FIELDS} for row in range(2)],
        }
    )


class FakeResponses:
    def __init__(self, parsed: VisionInvoiceCandidate | None = None, *, kind: str = "ok") -> None:
        self.parsed = parsed or VisionInvoiceCandidate.model_validate(
            {**{name: missing() for name in HEADER_FIELDS}, "line_items": []}
        )
        self.kind = kind
        self.requests: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        if self.kind == "exception":
            raise RuntimeError("SECRET provider body and credentials must not appear in reports")
        return SimpleNamespace(
            model="SECRET wrong-model" if self.kind == "wrong_model" else SUPPORTED_MODEL,
            service_tier="priority" if self.kind == "wrong_tier" else "default",
            status="incomplete" if self.kind == "incomplete" else "completed",
            output_parsed={} if self.kind == "bad_schema" else self.parsed,
            usage=(
                None
                if self.kind == "missing_usage"
                else SimpleNamespace(
                    input_tokens=100,
                    output_tokens=20,
                    total_tokens=999 if self.kind == "invalid_usage" else 120,
                )
            ),
            id="SECRET-response-id",
        )


def provider(responses: FakeResponses, limit: str = "2") -> BudgetedVisionProvider:
    return BudgetedVisionProvider(
        api_key="synthetic-key-not-a-credential",
        ledger=SpendLedger(PriceProfile(), Decimal(limit), 4096),
        client=SimpleNamespace(responses=responses),
    )


def test_corpus_reproducible_disjoint_labelled_and_ocr(cases: list[CorpusCase]) -> None:
    assert inventory(cases, 20261011) == inventory(generate_cases(20261011), 20261011)
    assert inventory(cases, 20261011) != inventory(generate_cases(123), 123)
    assert len(cases) == 16 and sum(c.pages for c in cases) == 17
    assert sum(len(c.truth.line_items) for c in cases) == 32
    assert set(FAMILIES["development"]).isdisjoint(FAMILIES["unseen"])
    assert sum(c.content_type == "image/png" for c in cases) == 2
    assert any(label.role == "unknown_amount" for c in cases for label in c.labels)
    assert any(label.role == "summary_total" for c in cases for label in c.labels)
    for case in cases:
        if case.content_type == "application/pdf":
            document = DocumentTextExtractor().extract(case.body, case.content_type)
            for label in case.labels:
                assert any(
                    label.bbox.x0 <= (w.bbox.x0 + w.bbox.x1) / 2 <= label.bbox.x1
                    and label.bbox.y0 <= (w.bbox.y0 + w.bbox.y1) / 2 <= label.bbox.y1
                    for w in document.pages[label.page].words
                )


def test_corpus_refuses_tampering_unsafe_paths_and_overwrite(repository: Path) -> None:
    root = repository / "work" / "hybrid-live-synthetic" / "fresh"
    write_corpus(root, repository, 20261011)
    manifest = root / "manifest.json"
    cases, fingerprint, seed = load_corpus(manifest, repository, "development")
    assert len(cases) == 8 and len(fingerprint) == 64
    assert seed == 20261011
    original = manifest.read_bytes()
    with pytest.raises(FileExistsError):
        write_corpus(root, repository, 20261011)
    assert manifest.read_bytes() == original
    with pytest.raises(ValueError):
        write_corpus(repository / "tracked", repository, 1)
    (root / cases[0].filename).write_bytes(b"NOT GENERATED / PRIVATE DOCUMENT")
    with pytest.raises(ValueError, match="Synthetic corpus verification failed"):
        load_corpus(manifest, repository, "development")


@pytest.mark.parametrize(
    "model,snapshot,today",
    [
        ("gpt-4.1-mini", PRICE_SNAPSHOT, date(2026, 10, 11)),
        (SUPPORTED_MODEL, "invented", date(2026, 10, 11)),
        (SUPPORTED_MODEL, PRICE_SNAPSHOT, date(2026, 10, 19)),
        (SUPPORTED_MODEL, PRICE_SNAPSHOT, date(2026, 10, 10)),
    ],
)
def test_unverified_or_stale_prices_refused(model: str, snapshot: str, today: date) -> None:
    with pytest.raises(ValueError):
        verified_profile(model, snapshot, today=today)


@pytest.mark.parametrize(
    "limit,output",
    [("0", 4096), ("0.1", 4096), ("NaN", 4096), ("Infinity", 4096), ("1", 0), ("1", 32769)],
)
def test_budget_preflight_refuses_unenforceable_limits(limit: str, output: int) -> None:
    with pytest.raises(ValueError):
        SpendLedger(PriceProfile(), Decimal(limit), output)


def test_bound_reserves_before_call_and_does_not_retry() -> None:
    responses = FakeResponses(kind="exception")
    bounded = provider(responses)
    with pytest.raises(VisionProviderError):
        bounded.extract([], SimpleNamespace())
    assert len(responses.requests) == 1
    assert bounded.ledger.accounted_upper == bounded.ledger.request_bound
    assert bounded.ledger.halted
    with pytest.raises(BudgetRefusal):
        bounded.extract([], SimpleNamespace())
    assert len(responses.requests) == 1
    assert bounded.ledger.accounted_upper <= bounded.ledger.limit


@pytest.mark.parametrize(
    "kind,known",
    [
        ("ok", True),
        ("incomplete", True),
        ("bad_schema", True),
        ("missing_usage", False),
        ("invalid_usage", False),
        ("wrong_model", False),
        ("wrong_tier", False),
    ],
)
def test_usage_failures_and_request_controls(kind: str, known: bool) -> None:
    responses = FakeResponses(kind=kind)
    bounded = provider(responses)
    try:
        bounded.extract([], SimpleNamespace())
    except VisionProviderError:
        assert kind in {"incomplete", "bad_schema", "wrong_model", "wrong_tier"}
    assert bounded.ledger.known_usage_calls == int(known)
    assert bounded.ledger.unknown_usage_calls == int(not known)
    assert bounded.ledger.halted == (not known)
    request = responses.requests[0]
    assert request["max_output_tokens"] == 4096
    assert request["service_tier"] == "default" and request["truncation"] == "disabled"
    assert request["tools"] == [] and request["store"] is False
    if known:
        assert bounded.ledger.input_tokens == 100 and bounded.ledger.total_tokens == 120
        assert bounded.ledger.known_cost == Decimal("0.000072")
        assert bounded.ledger.accounted_upper >= bounded.ledger.known_cost


def test_budget_exhaustion_refuses_before_second_request() -> None:
    bounded = provider(FakeResponses(), "0.6853832")
    bounded.extract([], SimpleNamespace())
    with pytest.raises(BudgetRefusal):
        bounded.extract([], SimpleNamespace())
    assert bounded.ledger.calls == 1


@pytest.mark.parametrize(
    "failure", ["authorization", "documents", "pages", "unseen", "output", "ocr"]
)
def test_all_corpus_preflight_failures_are_before_calls(
    repository: Path, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repository / "work" / "hybrid-live-synthetic" / "corpus"
    write_corpus(root, repository, 20261011)
    bounded = provider(FakeResponses())
    output = repository / "evals" / "reports" / "hybrid" / "fresh"
    kwargs: dict[str, Any] = {
        "allow_live": True,
        "max_documents": 16,
        "max_pages": 17,
        "output_dir": output,
        "repository": repository,
        "allow_holdout": True,
    }
    if failure == "authorization":
        kwargs["allow_live"] = False
    elif failure == "documents":
        kwargs["max_documents"] = 15
    elif failure == "pages":
        kwargs["max_pages"] = 16
    elif failure == "unseen":
        kwargs["allow_holdout"] = False
    elif failure == "output":
        output.mkdir(parents=True)
    elif failure == "ocr":
        monkeypatch.setattr(
            "invoiceops.evaluation.hybrid_live.inspect_ocr_runtime",
            lambda: SimpleNamespace(available=False),
        )
    with pytest.raises((ValueError, RuntimeError, FileExistsError)):
        run_hybrid_live_manifest(root / "manifest.json", bounded, PageRenderer(), **kwargs)
    assert bounded.ledger.calls == 0


def test_live_paired_report_failures_privacy_accounting_and_overwrite(repository: Path) -> None:
    root = repository / "work" / "hybrid-live-synthetic" / "corpus"
    write_corpus(root, repository, 20261011)
    output = repository / "evals" / "reports" / "hybrid" / "fresh"
    bounded = provider(FakeResponses(kind="exception"))
    report = run_hybrid_live_manifest(
        root / "manifest.json",
        bounded,
        PageRenderer(),
        allow_live=True,
        max_documents=8,
        max_pages=8,
        output_dir=output,
        repository=repository,
        partition="development",
    )
    assert report.mode == "fake-provider" and report.documents == 8
    metrics = report.metrics["all"]
    assert metrics.deterministic.documents == metrics.hybrid.documents == 8
    assert metrics.deterministic.header_exact_match == metrics.hybrid.header_exact_match
    assert metrics.safety.provider_requests == metrics.safety.provider_failures == 1
    assert metrics.safety.budget_refused_documents == metrics.safety.eligible_documents - 1
    assert (
        report.usage.estimated_total_cost_usd is None and report.usage.unknown_usage_requests == 1
    )
    assert report.usage.accounting_halted
    content = (output / "report.json").read_text(encoding="utf-8")
    assert json.loads(content) == report.model_dump(mode="json")
    assert "denominator" in (output / "report.md").read_text()
    for secret in (
        "SECRET",
        str(repository),
        "manifest.json",
        "SYN-LIVE-",
        "Synthetic component",
        "evidence_quote",
        "output_parsed",
        "case-000",
        "document_id",
        "image_bytes",
    ):
        assert secret not in content
    original = (output / "report.json").read_bytes()
    with pytest.raises(FileExistsError):
        run_hybrid_live_manifest(
            root / "manifest.json",
            bounded,
            PageRenderer(),
            allow_live=True,
            max_documents=8,
            max_pages=8,
            output_dir=output,
            repository=repository,
            partition="development",
        )
    assert (output / "report.json").read_bytes() == original
    assert bounded.ledger.calls == 1
    with pytest.raises(ValidationError):
        LiveReport.model_validate({**report.model_dump(), "private_notes": "SECRET"})
    with pytest.raises(ValueError):
        output_preflight(repository / "other", repository)


def test_grounded_role_error_is_counted_even_if_matching_arithmetic_passes(
    cases: list[CorpusCase],
) -> None:
    case = next(c for c in cases if c.family == "ambiguous")
    baseline = labelled_baseline(case)
    document = DocumentTextExtractor().extract(case.body, case.content_type)
    proposed = candidate(case)
    rows = []
    for row in range(2):
        labels = [label for label in case.labels if label.row == row]
        net = next(label for label in labels if label.role == "unknown_amount")
        quote = " ".join(label.value for label in sorted(labels, key=lambda label: label.bbox.x0))
        rows.append(
            proposed.line_items[row].model_copy(
                update={
                    "line_total": CandidateField(
                        raw_value=net.value, page=net.page, evidence_quote=quote
                    )
                }
            )
        )
    proposed = proposed.model_copy(update={"line_items": rows})
    fused = fuse_invoice(baseline, proposed, document)
    audit = _combine([audit_fusion(case, baseline, document, proposed, fused)], [])
    assert audit.grounded_values > 0
    assert audit.correct_associations == 2
    assert audit.false_financial_promotions.numerator == audit.numeric_promoted_cells == 2
    assert audit.wrong_financial_role_promotions == 2
    assert audit.false_cross_row_promotions.numerator == 0
    metrics = mode_counts([case], [fused.invoice], [1.0])
    # This is a measured financial-role limitation, not a new production policy gate.
    assert metrics.false_automatic_matches.numerator == metrics.expected_review_documents == 1


@pytest.mark.parametrize("kind", ["reordered", "cross_row", "missing", "duplicate"])
def test_row_association_safety_and_denominators(cases: list[CorpusCase], kind: str) -> None:
    case = cases[0]
    baseline = labelled_baseline(case)
    for line in baseline.line_items:
        line.quantity = line.quantity.model_copy(
            update={"value": None, "status": ExtractionStatus.MISSING, "evidence": []}
        )
    proposed = candidate(case)
    rows = proposed.line_items
    if kind == "reordered":
        rows = rows[::-1]
    elif kind == "cross_row":
        rows = [rows[0].model_copy(update={"quantity": rows[1].quantity}), rows[1]]
    elif kind == "missing":
        rows = rows[:1]
    else:
        rows = [rows[0], rows[0], rows[1]]
    proposed = proposed.model_copy(update={"line_items": rows})
    document = DocumentTextExtractor().extract(case.body, case.content_type)
    fused = fuse_invoice(baseline, proposed, document)
    audit = _combine([audit_fusion(case, baseline, document, proposed, fused)], [])
    assert audit.incorrect_associations == 0
    assert audit.false_financial_promotions.numerator == 0
    assert audit.false_cross_row_promotions.numerator == 0
    assert audit.row_association_precision.denominator == audit.associated_rows
    assert audit.deterministic_row_association_coverage.denominator == 2
    assert audit.row_abstention.numerator + audit.associated_rows == len(rows)
    if kind != "reordered":
        assert fused.invoice.extraction_issues
        metrics = mode_counts([case], [fused.invoice], [1.0])
        assert metrics.review_documents == 1 and metrics.false_automatic_matches.numerator == 0


def test_null_rates_and_reordered_exact_line_multiset(cases: list[CorpusCase]) -> None:
    baseline = labelled_baseline(cases[0])
    baseline.line_items.reverse()
    counts = mode_counts([cases[0]], [baseline], [1.0])
    assert counts.line_tp == counts.labelled_lines == counts.predicted_lines == 2
    assert counts.line_precision.rate == counts.line_recall.rate == counts.line_f1.rate == 1
    assert _combine([], []).row_association_precision.rate is None


def test_cli_live_without_authorization_is_network_free() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_hybrid_evaluation.py", "--mode", "hybrid-live"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2 and "requires --allow-live" in result.stderr


def test_sdk_constructor_pins_endpoint_no_proxy_no_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    import openai

    observed: dict[str, Any] = {}

    def construct(**kwargs: Any) -> SimpleNamespace:
        observed.update(kwargs)
        return SimpleNamespace(responses=FakeResponses(), close=kwargs["http_client"].close)

    monkeypatch.setattr(openai, "OpenAI", construct)
    monkeypatch.setattr(
        "invoiceops.evaluation.live_budget.verified_profile",
        lambda model, snapshot: verified_profile(model, snapshot, today=date(2026, 10, 11)),
    )
    monkeypatch.setenv("OPENAI_BASE_URL", "https://secret.invalid")
    monkeypatch.setenv("HTTP_PROXY", "http://secret.invalid")
    bounded = BudgetedVisionProvider(
        api_key="synthetic-key", ledger=SpendLedger(PriceProfile(), Decimal(2), 4096)
    )
    assert observed["base_url"] == "https://api.openai.com/v1"
    assert observed["max_retries"] == bounded._provider.max_retries == 0
    assert observed["http_client"].follow_redirects is False
    assert observed["http_client"]._trust_env is False
    bounded.close()


@pytest.mark.parametrize("setting", ["debug", "info", "logger"])
def test_verbose_logging_refuses_before_sdk_initialization(
    monkeypatch: pytest.MonkeyPatch,
    setting: str,
) -> None:
    if setting != "logger":
        monkeypatch.setenv("OPENAI_LOG", setting)
    else:
        monkeypatch.delenv("OPENAI_LOG", raising=False)
        original = logging.Logger.isEnabledFor
        monkeypatch.setattr(
            logging.Logger,
            "isEnabledFor",
            lambda logger, level: (
                True if logger.name == "openai._base_client" else original(logger, level)
            ),
        )
    with pytest.raises(ValueError, match="logging is unsafe"):
        BudgetedVisionProvider(
            api_key="synthetic-key", ledger=SpendLedger(PriceProfile(), Decimal(2), 4096)
        )


def test_full_paired_partitions_ocr_provenance_and_known_usage(
    repository: Path, cases: list[CorpusCase]
) -> None:
    root = repository / "work" / "hybrid-live-synthetic" / "corpus"
    write_corpus(root, repository, 20261011)
    renderer = PageRenderer()
    by_image = {
        hashlib.sha256(renderer.render(c.body, c.content_type)[0].image_bytes).hexdigest(): c
        for c in cases
    }

    class FactoryResponses(FakeResponses):
        def parse(self, **kwargs: Any) -> SimpleNamespace:
            image = kwargs["input"][1]["content"][1]["image_url"].split(",", 1)[1]
            case = by_image[hashlib.sha256(base64.b64decode(image)).hexdigest()]
            self.parsed = candidate(case)
            return super().parse(**kwargs)

    class SyntheticOcr(DocumentTextExtractor):
        def extract(self, body: bytes, content_type: str) -> DocumentText:
            if content_type == "application/pdf":
                return super().extract(body, content_type)
            case = next(c for c in cases if c.body == body)
            words = [
                WordToken(
                    text=label.value,
                    page=0,
                    bbox=label.bbox,
                    source=TextSource.OCR,
                    block_number=0,
                    line_number=i,
                    word_number=i,
                )
                for i, label in enumerate(case.labels)
            ]
            # Known synthetic OCR is test-only; production OCR is never replaced by labels.
            for i, label in enumerate(case.labels):
                if label.row is None:
                    words.append(
                        WordToken(
                            text=label.role.replace("_", " ") + ":",
                            page=0,
                            source=TextSource.OCR,
                            bbox=BoundingBox(
                                x0=max(0, label.bbox.x0 - 0.16),
                                x1=label.bbox.x0 - 0.005,
                                y0=label.bbox.y0,
                                y1=label.bbox.y1,
                            ),
                            block_number=0,
                            line_number=i,
                            word_number=0,
                        )
                    )
            return DocumentText(
                pages=[
                    PageText(
                        page=0,
                        width=700,
                        height=700,
                        source=TextSource.OCR,
                        ocr_reason=OcrReason.NO_EMBEDDED_TEXT,
                        words=words,
                    )
                ],
                used_ocr=True,
            )

    bounded = provider(FactoryResponses())
    report = run_hybrid_live_manifest(
        root / "manifest.json",
        bounded,
        renderer,
        allow_live=True,
        allow_holdout=True,
        max_documents=16,
        max_pages=17,
        repository=repository,
        output_dir=repository / "evals" / "reports" / "hybrid" / "full",
        text_extractor=SyntheticOcr(),
    )
    assert report.documents == 16 and report.pages == 17 and report.ocr_documents == 2
    assert set(report.metrics) == {"all", "development", "unseen"}
    all_metrics = report.metrics["all"]
    assert all_metrics.deterministic.documents == all_metrics.hybrid.documents == 16
    assert all_metrics.deterministic.labelled_lines == all_metrics.hybrid.labelled_lines == 32
    for mode in ("deterministic", "hybrid"):
        combined = getattr(all_metrics, mode)
        dev = getattr(report.metrics["development"], mode)
        unseen = getattr(report.metrics["unseen"], mode)
        assert combined.line_tp == dev.line_tp + unseen.line_tp
        assert combined.line_fp == dev.line_fp + unseen.line_fp
        assert combined.line_fn == dev.line_fn + unseen.line_fn
        assert all(rate.denominator == 16 for rate in combined.header_exact_match.values())
    assert all_metrics.safety.successful_responses == report.usage.requests > 0
    assert report.usage.requests == report.usage.known_usage_requests
    assert report.usage.input_tokens == 100 * report.usage.requests
    assert report.usage.complete and not report.usage.accounting_halted
    assert all_metrics.safety.incorrect_associations == 0
    assert all_metrics.safety.false_cross_row_promotions.numerator == 0
    assert all_metrics.safety.unresolved_row_false_automatic_matches.numerator == 0
    assert (
        all_metrics.safety.unresolved_row_review_documents
        == all_metrics.safety.unresolved_row_documents
    )


def test_live_cli_wiring_uses_explicit_model_budget_without_enabling_production(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from pydantic import SecretStr

    from scripts import run_hybrid_evaluation as cli

    root = repository / "work" / "hybrid-live-synthetic" / "corpus"
    write_corpus(root, repository, 20261011)
    # Keep the entire integration in the temporary guarded repository.
    monkeypatch.setattr(cli, "__file__", str(repository / "scripts" / "runner.py"))
    output = repository / "evals" / "reports" / "hybrid" / "cli"
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(
            vlm_enabled=False,
            openai_api_key=SecretStr("synthetic-key"),
            vlm_timeout_seconds=1,
        ),
    )
    monkeypatch.setattr(
        cli,
        "verified_profile",
        lambda model, snapshot: verified_profile(
            model,
            snapshot,
            today=date(2026, 10, 11),
        ),
    )
    monkeypatch.setattr(
        cli,
        "BudgetedVisionProvider",
        lambda **kwargs: BudgetedVisionProvider(
            **kwargs,
            client=SimpleNamespace(responses=FakeResponses()),
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_hybrid_evaluation.py",
            "--mode",
            "hybrid-live",
            "--allow-live",
            "--manifest",
            str(root / "manifest.json"),
            "--output-dir",
            str(output),
            "--model",
            SUPPORTED_MODEL,
            "--max-documents",
            "8",
            "--max-pages",
            "8",
            "--partition",
            "development",
            "--max-spend-usd",
            "2",
            "--max-output-tokens",
            "4096",
            "--confirm-price-snapshot",
            PRICE_SNAPSHOT,
        ],
    )
    cli.main()
    report = LiveReport.model_validate_json((output / "report.json").read_bytes())
    assert report.mode == "fake-provider" and report.usage.requests > 0
    assert report.usage.spending_limit_usd == "2"
    assert report.price_assumptions.model == SUPPORTED_MODEL
    assert report.documents == 8
    assert "synthetic-key" not in capsys.readouterr().out


def test_source_roles_cannot_receive_duplicate_truth_credit(cases: list[CorpusCase]) -> None:
    baseline = labelled_baseline(cases[0])
    baseline.line_items = [baseline.line_items[0], baseline.line_items[0]]
    counts = mode_counts([cases[0]], [baseline], [1.0])
    assert (counts.line_tp, counts.line_fp, counts.line_fn) == (1, 1, 1)
    invalid = replace(cases[0], labels=())
    assert (
        mode_counts(
            [invalid], [labelled_baseline(cases[0])], [1.0]
        ).false_automatic_matches.numerator
        == 1
    )
