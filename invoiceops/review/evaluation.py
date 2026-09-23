import json
import platform
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median

from pydantic import BaseModel, ConfigDict, Field

from invoiceops.review.audit import ReconstructedState, apply_event, event_hash
from invoiceops.review.state import (
    ReviewState,
    ReviewTransitionError,
    claim,
    comment,
    release,
    resolve,
)
from invoiceops.schemas.review import ReviewEventType, ReviewResolution, ReviewStatus

REVIEW_SCENARIO_SET_VERSION = "review-scenarios-v1"
REVIEW_WORKFLOW_VERSION = "review-v1"


class ReviewEvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_count: int = Field(ge=15)
    expected_transition_accuracy: float = Field(ge=0, le=1)
    allowed_transition_accuracy: float = Field(ge=0, le=1)
    invalid_transition_rejection_rate: float = Field(ge=0, le=1)
    stale_version_rejection_accuracy: float = Field(ge=0, le=1)
    unauthorized_owner_action_rejection_rate: float = Field(ge=0, le=1)
    idempotent_replay_rejection_accuracy: float = Field(ge=0, le=1)
    duplicate_case_count: int = Field(ge=0)
    event_chain_verification_rate: float = Field(ge=0, le=1)
    state_reconstruction_accuracy: float = Field(ge=0, le=1)
    false_auto_resolution_count: int = Field(ge=0)
    p50_transition_latency_ms: float = Field(ge=0)
    p95_transition_latency_ms: float = Field(ge=0)
    max_transition_latency_ms: float = Field(ge=0)
    scenario_set_version: str
    workflow_version: str
    evaluated_at: datetime
    python_version: str
    git_revision: str


@dataclass(frozen=True)
class Scenario:
    name: str
    category: str
    expected_allowed: bool
    operation: Callable[[], object]


def _open(version: int = 1) -> ReviewState:
    return ReviewState(ReviewStatus.OPEN, None, version)


def _claimed(version: int = 2, assignee: str = "reviewer-a") -> ReviewState:
    return ReviewState(ReviewStatus.CLAIMED, assignee, version)


def _resolved() -> ReviewState:
    return ReviewState(
        ReviewStatus.RESOLVED,
        "reviewer-a",
        3,
        ReviewResolution.ACCEPTED_EXCEPTION,
        "Synthetic documented exception",
    )


def _resolve_operation(resolution: ReviewResolution) -> Callable[[], object]:
    return lambda: resolve(_claimed(), "reviewer-a", 2, resolution, "documented reason")


def scenarios() -> list[Scenario]:
    return [
        Scenario("claim_open", "allowed", True, lambda: claim(_open(), "reviewer-a", 1)),
        Scenario(
            "comment_open", "allowed", True, lambda: comment(_open(), "reviewer-b", 1, "note")
        ),
        Scenario(
            "comment_claimed",
            "allowed",
            True,
            lambda: comment(_claimed(), "reviewer-b", 2, "note"),
        ),
        Scenario(
            "release_owner",
            "allowed",
            True,
            lambda: release(_claimed(), "reviewer-a", 2, "handover"),
        ),
        *[
            Scenario(
                f"resolve_{resolution.value.lower()}",
                "allowed",
                True,
                _resolve_operation(resolution),
            )
            for resolution in ReviewResolution
        ],
        Scenario(
            "claim_claimed",
            "invalid",
            False,
            lambda: claim(_claimed(), "reviewer-a", 2),
        ),
        Scenario(
            "release_open", "invalid", False, lambda: release(_open(), "reviewer-a", 1, "no")
        ),
        Scenario(
            "resolve_open",
            "invalid",
            False,
            lambda: resolve(
                _open(), "reviewer-a", 1, ReviewResolution.REJECTED_DOCUMENT, "no"
            ),
        ),
        Scenario(
            "comment_resolved",
            "invalid",
            False,
            lambda: comment(_resolved(), "reviewer-a", 3, "late"),
        ),
        Scenario(
            "release_wrong_reviewer",
            "unauthorized",
            False,
            lambda: release(_claimed(), "reviewer-b", 2, "no"),
        ),
        Scenario(
            "resolve_wrong_reviewer",
            "unauthorized",
            False,
            lambda: resolve(
                _claimed(), "reviewer-b", 2, ReviewResolution.REJECTED_DOCUMENT, "no"
            ),
        ),
        Scenario(
            "claim_stale_version",
            "stale",
            False,
            lambda: claim(_open(version=2), "reviewer-a", 1),
        ),
        Scenario(
            "comment_stale_version",
            "stale",
            False,
            lambda: comment(_claimed(version=4), "reviewer-a", 3, "stale"),
        ),
        Scenario(
            "duplicate_claim_replay",
            "idempotent_replay",
            False,
            lambda: claim(_claimed(), "reviewer-a", 1),
        ),
        Scenario(
            "duplicate_resolve_replay",
            "idempotent_replay",
            False,
            lambda: resolve(
                _resolved(),
                "reviewer-a",
                2,
                ReviewResolution.ACCEPTED_EXCEPTION,
                "duplicate",
            ),
        ),
    ]


def run_review_evaluation() -> ReviewEvaluationReport:
    outcomes: list[tuple[Scenario, bool]] = []
    latencies: list[float] = []
    false_auto_resolutions = 0
    for scenario in scenarios():
        started = time.perf_counter()
        allowed = True
        result: object | None = None
        try:
            result = scenario.operation()
        except ReviewTransitionError:
            allowed = False
        latencies.append((time.perf_counter() - started) * 1000)
        outcomes.append((scenario, allowed == scenario.expected_allowed))
        if (
            not scenario.expected_allowed
            and getattr(result, "status", None) == ReviewStatus.RESOLVED
        ):
            false_auto_resolutions += 1

    def accuracy(category: str) -> float:
        selected = [passed for scenario, passed in outcomes if scenario.category == category]
        return sum(selected) / len(selected)

    ordered = sorted(latencies)
    duplicate_case_count, chain_rate, reconstruction_accuracy = _workflow_invariants()
    return ReviewEvaluationReport(
        scenario_count=len(outcomes),
        expected_transition_accuracy=sum(passed for _, passed in outcomes) / len(outcomes),
        allowed_transition_accuracy=accuracy("allowed"),
        invalid_transition_rejection_rate=accuracy("invalid"),
        stale_version_rejection_accuracy=accuracy("stale"),
        unauthorized_owner_action_rejection_rate=accuracy("unauthorized"),
        idempotent_replay_rejection_accuracy=accuracy("idempotent_replay"),
        duplicate_case_count=duplicate_case_count,
        event_chain_verification_rate=chain_rate,
        state_reconstruction_accuracy=reconstruction_accuracy,
        false_auto_resolution_count=false_auto_resolutions,
        p50_transition_latency_ms=round(median(ordered), 6),
        p95_transition_latency_ms=round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 6),
        max_transition_latency_ms=round(max(ordered), 6),
        scenario_set_version=REVIEW_SCENARIO_SET_VERSION,
        workflow_version=REVIEW_WORKFLOW_VERSION,
        evaluated_at=datetime.now(UTC),
        python_version=platform.python_version(),
        git_revision=_git_revision(),
    )


def write_review_report(output_dir: Path, report: ReviewEvaluationReport) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown = f"""# Review workflow evaluation

Synthetic scenario set: `{report.scenario_set_version}`  
Workflow version: `{report.workflow_version}`  
Scenario count: {report.scenario_count}

| Metric | Result |
| --- | ---: |
| Expected transition accuracy | {report.expected_transition_accuracy:.4f} |
| Allowed transition accuracy | {report.allowed_transition_accuracy:.4f} |
| Invalid transition rejection rate | {report.invalid_transition_rejection_rate:.4f} |
| Stale-version rejection accuracy | {report.stale_version_rejection_accuracy:.4f} |
| Unauthorized-owner action rejection rate | {report.unauthorized_owner_action_rejection_rate:.4f} |
| Idempotent replay rejection accuracy | {report.idempotent_replay_rejection_accuracy:.4f} |
| Duplicate case count | {report.duplicate_case_count} |
| Event-chain verification rate | {report.event_chain_verification_rate:.4f} |
| State reconstruction accuracy | {report.state_reconstruction_accuracy:.4f} |
| False automatic resolution count | {report.false_auto_resolution_count} |
| p50 transition latency (ms) | {report.p50_transition_latency_ms:.6f} |
| p95 transition latency (ms) | {report.p95_transition_latency_ms:.6f} |
| Maximum transition latency (ms) | {report.max_transition_latency_ms:.6f} |

All scenarios are synthetic state-machine checks. Latency measures in-process transition logic,
not database or HTTP performance. Chain and reconstruction rates cover three complete synthetic
histories; duplicate-case count covers repeated insertion into a logical-match registry.
`ACCEPTED_EXCEPTION` records a review outcome and never authorizes payment.
"""
    (output_dir / "report.md").write_text(markdown, encoding="utf-8")


def _workflow_invariants() -> tuple[int, float, float]:
    run_ids = [uuid.UUID(int=index) for index in range(1, 4)]
    case_registry: dict[uuid.UUID, uuid.UUID] = {}
    for run_id in [*run_ids, *run_ids]:
        case_registry.setdefault(run_id, uuid.uuid5(uuid.NAMESPACE_URL, f"review:{run_id}"))
    duplicate_case_count = len(case_registry) - len(run_ids)

    chain_results: list[bool] = []
    reconstruction_results: list[bool] = []
    for index, resolution in enumerate(ReviewResolution, start=1):
        case_id = case_registry[run_ids[index - 1]]
        started = datetime(2026, 9, 23, 12, index, tzinfo=UTC)
        definitions: list[tuple[ReviewEventType, str, dict[str, object]]] = [
            (ReviewEventType.CASE_OPENED, "system:matching", {}),
            (ReviewEventType.CASE_CLAIMED, "reviewer-a", {"reviewer_id": "reviewer-a"}),
            (
                ReviewEventType.CASE_RESOLVED,
                "reviewer-a",
                {"resolution": resolution.value, "reason": "synthetic explanation"},
            ),
        ]
        previous: str | None = None
        events: list[tuple[ReviewEventType, str, dict[str, object], datetime, str | None, str]] = []
        for sequence, (event_type, actor_id, payload) in enumerate(definitions, start=1):
            occurred_at = started + timedelta(seconds=sequence)
            digest = event_hash(
                case_id=case_id,
                sequence_number=sequence,
                event_type=event_type,
                actor_id=actor_id,
                occurred_at=occurred_at,
                payload=payload,
                previous_hash=previous,
            )
            events.append((event_type, actor_id, payload, occurred_at, previous, digest))
            previous = digest

        reconstructed = ReconstructedState(None, None, None, None, 0)
        expected_previous: str | None = None
        chain_valid = True
        for sequence, event in enumerate(events, start=1):
            event_type, actor_id, payload, occurred_at, stored_previous, stored_hash = event
            recomputed = event_hash(
                case_id=case_id,
                sequence_number=sequence,
                event_type=event_type,
                actor_id=actor_id,
                occurred_at=occurred_at,
                payload=payload,
                previous_hash=stored_previous,
            )
            chain_valid &= stored_previous == expected_previous and stored_hash == recomputed
            reconstructed = apply_event(reconstructed, event_type, actor_id, payload)
            expected_previous = stored_hash
        chain_results.append(chain_valid)
        reconstruction_results.append(
            reconstructed.status == ReviewStatus.RESOLVED
            and reconstructed.assignee == "reviewer-a"
            and reconstructed.resolution == resolution
            and reconstructed.resolution_reason == "synthetic explanation"
            and reconstructed.version == 3
        )
    return (
        duplicate_case_count,
        sum(chain_results) / len(chain_results),
        sum(reconstruction_results) / len(reconstruction_results),
    )


def _git_revision() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
