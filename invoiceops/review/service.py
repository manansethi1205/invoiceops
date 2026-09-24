import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from invoiceops.models import (
    ExtractionRun,
    MatchRun,
    ReviewCase,
    ReviewCaseTrigger,
    ReviewEvent,
    RiskAssessment,
)
from invoiceops.review.audit import (
    AUDIT_HASH_V2,
    ReconstructedState,
    UnsupportedAuditHashVersionError,
    apply_event,
    event_hash,
)
from invoiceops.review.state import (
    ReviewState,
    ReviewTransitionError,
    Transition,
    claim,
    comment,
    release,
    resolve,
)
from invoiceops.schemas.matching import MatchDecision, MatchResult, ReasonCode
from invoiceops.schemas.review import (
    AuditVerificationRead,
    ReviewCaseDetail,
    ReviewCasePage,
    ReviewCaseRead,
    ReviewEventRead,
    ReviewEventType,
    ReviewResolution,
    ReviewStatus,
    ReviewTriggerRead,
    ReviewTriggerType,
)
from invoiceops.schemas.risk import RiskDisposition

SYSTEM_ACTOR_ID = "system:matching"
MATCH_REASON_TRIGGER = "MATCH_REASON"
RISK_SIGNAL_TRIGGER = "RISK_SIGNAL"


class ReviewCaseNotFoundError(LookupError):
    pass


class InvalidReviewCursorError(ValueError):
    pass


@dataclass(frozen=True)
class ReconciliationResult:
    inspected: int
    created: int
    already_present: int


def _now() -> datetime:
    return datetime.now(UTC)


def _reason_codes(run: MatchRun) -> list[ReasonCode]:
    return MatchResult.model_validate(run.result_json).reason_codes


def review_case_to_read(case: ReviewCase) -> ReviewCaseRead:
    return ReviewCaseRead(
        id=case.id,
        match_run_id=case.match_run_id,
        status=case.status,
        assigned_reviewer_id=case.assigned_reviewer_id,
        version=case.version,
        opened_at=case.opened_at,
        claimed_at=case.claimed_at,
        resolved_at=case.resolved_at,
        resolution=case.resolution,
        resolution_reason=case.resolution_reason,
        reason_codes=_reason_codes(case.match_run),
        review_triggers=[
            ReviewTriggerRead(
                id=trigger.id,
                type=ReviewTriggerType(trigger.trigger_type),
                code=trigger.trigger_code,
                source_id=trigger.source_id,
                source_url=(
                    f"/v1/risk-assessments/{trigger.source_id}"
                    if trigger.trigger_type == RISK_SIGNAL_TRIGGER
                    else f"/v1/matches/{trigger.source_id}"
                ),
                created_at=trigger.created_at,
            )
            for trigger in sorted(
                case.triggers,
                key=lambda item: (item.trigger_type, item.trigger_code, str(item.source_id)),
            )
        ],
    )


def review_event_to_read(event: ReviewEvent) -> ReviewEventRead:
    return ReviewEventRead(
        id=event.id,
        review_case_id=event.review_case_id,
        sequence_number=event.sequence_number,
        event_type=event.event_type,
        actor_id=event.actor_id,
        payload=event.payload,
        hash_version=event.hash_version,
        previous_hash=event.previous_hash,
        event_hash=event.event_hash,
        occurred_at=event.occurred_at,
    )


def ensure_review_case(
    session: Session,
    run: MatchRun,
    risk_assessment: RiskAssessment | None = None,
) -> tuple[ReviewCase | None, bool]:
    """Ensure matching/risk review routing exists without committing."""
    requires_review = run.decision == MatchDecision.NEEDS_REVIEW or (
        risk_assessment is not None
        and risk_assessment.disposition == RiskDisposition.NEEDS_REVIEW
    )
    if not requires_review:
        return None, False
    existing = session.scalar(
        select(ReviewCase).where(ReviewCase.match_run_id == run.id)
    )
    if existing is not None:
        _ensure_review_triggers(session, existing, run, risk_assessment)
        session.flush()
        return existing, False

    occurred_at = _now()
    case = ReviewCase(
        id=uuid.uuid4(),
        match_run_id=run.id,
        status=ReviewStatus.OPEN,
        version=1,
        opened_at=occurred_at,
    )
    trigger_snapshot = _trigger_snapshot(run, risk_assessment)
    payload: dict[str, object] = {
        "match_run_id": str(run.id),
        "reason_codes": [code.value for code in _reason_codes(run)],
        "review_triggers": trigger_snapshot,
    }
    event = ReviewEvent(
        id=uuid.uuid4(),
        review_case_id=case.id,
        sequence_number=1,
        event_type=ReviewEventType.CASE_OPENED,
        actor_id=SYSTEM_ACTOR_ID,
        payload=payload,
        hash_version=AUDIT_HASH_V2,
        previous_hash=None,
        event_hash=event_hash(
            case_id=case.id,
            sequence_number=1,
            event_type=ReviewEventType.CASE_OPENED,
            actor_id=SYSTEM_ACTOR_ID,
            occurred_at=occurred_at,
            payload=payload,
            previous_hash=None,
            hash_version=AUDIT_HASH_V2,
        ),
        occurred_at=occurred_at,
    )
    session.add_all((case, event))
    _ensure_review_triggers(session, case, run, risk_assessment)
    session.flush()
    return case, True


def _trigger_snapshot(
    run: MatchRun, risk_assessment: RiskAssessment | None
) -> list[dict[str, str]]:
    triggers = [
        {
            "type": MATCH_REASON_TRIGGER,
            "code": reason.value,
            "source_id": str(run.id),
        }
        for reason in _reason_codes(run)
    ]
    if risk_assessment is not None:
        triggers.extend(
            {
                "type": RISK_SIGNAL_TRIGGER,
                "code": signal.code.value,
                "source_id": str(risk_assessment.id),
            }
            for signal in risk_assessment.signals
        )
    unique = {
        (item["type"], item["code"], item["source_id"]): item for item in triggers
    }
    return sorted(
        unique.values(), key=lambda item: (item["type"], item["code"], item["source_id"])
    )


def _ensure_review_triggers(
    session: Session,
    case: ReviewCase,
    run: MatchRun,
    risk_assessment: RiskAssessment | None,
) -> None:
    existing = set(
        session.scalars(
            select(ReviewCaseTrigger).where(
                ReviewCaseTrigger.review_case_id == case.id,
            )
        )
    )
    existing_keys = {
        (trigger.trigger_type, trigger.trigger_code, trigger.source_id)
        for trigger in existing
    }
    for trigger in _trigger_snapshot(run, risk_assessment):
        key = (
            trigger["type"],
            trigger["code"],
            uuid.UUID(trigger["source_id"]),
        )
        if key not in existing_keys:
            session.add(
                ReviewCaseTrigger(
                    review_case_id=case.id,
                    trigger_type=key[0],
                    trigger_code=key[1],
                    source_id=key[2],
                    created_at=case.opened_at,
                )
            )


class ReviewService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, case_id: uuid.UUID) -> ReviewCase:
        case = self.session.scalar(
            select(ReviewCase)
            .where(ReviewCase.id == case_id)
            .options(selectinload(ReviewCase.match_run), selectinload(ReviewCase.triggers))
        )
        if case is None:
            raise ReviewCaseNotFoundError
        return case

    def detail(
        self, case_id: uuid.UUID, *, events_url: str, audit_verification_url: str
    ) -> ReviewCaseDetail:
        case = self.get(case_id)
        extraction = self.session.get(ExtractionRun, case.match_run.extraction_run_id)
        if extraction is None:  # Protected by the foreign key; retained as a corruption guard.
            raise RuntimeError("Review case references a missing extraction run")
        from invoiceops.matching.service import match_run_to_read

        base = review_case_to_read(case)
        return ReviewCaseDetail(
            **base.model_dump(),
            match=match_run_to_read(case.match_run),
            extraction_name=extraction.extractor_name,
            extraction_version=extraction.extractor_version,
            events_url=events_url,
            audit_verification_url=audit_verification_url,
        )

    def list_cases(
        self,
        *,
        status: ReviewStatus | None = None,
        assignee: str | None = None,
        reason_code: ReasonCode | None = None,
        trigger_type: ReviewTriggerType | None = None,
        trigger_code: str | None = None,
        created_before: datetime | None = None,
        created_after: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> ReviewCasePage:
        statement: Select[tuple[ReviewCase]] = select(ReviewCase).options(
            selectinload(ReviewCase.match_run), selectinload(ReviewCase.triggers)
        )
        if status is not None:
            statement = statement.where(ReviewCase.status == status)
        if assignee is not None:
            statement = statement.where(ReviewCase.assigned_reviewer_id == assignee)
        if created_before is not None:
            statement = statement.where(ReviewCase.opened_at < created_before)
        if created_after is not None:
            statement = statement.where(ReviewCase.opened_at >= created_after)
        if cursor is not None:
            opened_at, case_id = _decode_cursor(cursor)
            statement = statement.where(
                or_(
                    ReviewCase.opened_at < opened_at,
                    and_(ReviewCase.opened_at == opened_at, ReviewCase.id < case_id),
                )
            )
        statement = statement.order_by(ReviewCase.opened_at.desc(), ReviewCase.id.desc())

        effective_type = trigger_type
        effective_code = trigger_code
        if reason_code is not None:
            if effective_type is not None and effective_type != ReviewTriggerType.MATCH_REASON:
                return ReviewCasePage(items=[], next_cursor=None)
            if effective_code is not None and effective_code != reason_code.value:
                return ReviewCasePage(items=[], next_cursor=None)
            effective_type = ReviewTriggerType.MATCH_REASON
            effective_code = reason_code.value
        if effective_type is not None or effective_code is not None:
            statement = statement.join(
                ReviewCaseTrigger,
                ReviewCaseTrigger.review_case_id == ReviewCase.id,
            )
            if effective_type is not None:
                statement = statement.where(
                    ReviewCaseTrigger.trigger_type == effective_type.value
                )
            if effective_code is not None:
                statement = statement.where(ReviewCaseTrigger.trigger_code == effective_code)
        candidates = list(self.session.scalars(statement.limit(limit + 1)))
        page = candidates
        has_more = len(page) > limit
        page = page[:limit]
        next_cursor = _encode_cursor(page[-1]) if has_more else None
        return ReviewCasePage(
            items=[review_case_to_read(case) for case in page], next_cursor=next_cursor
        )

    def claim(self, case_id: uuid.UUID, actor_id: str, expected_version: int) -> ReviewCase:
        case = self.get(case_id)
        return self._apply(case, claim(self._state(case), actor_id, expected_version), actor_id)

    def release(
        self, case_id: uuid.UUID, actor_id: str, expected_version: int, reason: str
    ) -> ReviewCase:
        case = self.get(case_id)
        transition = release(self._state(case), actor_id, expected_version, reason)
        return self._apply(case, transition, actor_id)

    def comment(
        self, case_id: uuid.UUID, actor_id: str, expected_version: int, text: str
    ) -> ReviewCase:
        case = self.get(case_id)
        transition = comment(self._state(case), actor_id, expected_version, text)
        return self._apply(case, transition, actor_id)

    def resolve(
        self,
        case_id: uuid.UUID,
        actor_id: str,
        expected_version: int,
        resolution: ReviewResolution,
        reason: str,
    ) -> ReviewCase:
        case = self.get(case_id)
        transition = resolve(
            self._state(case), actor_id, expected_version, resolution, reason
        )
        return self._apply(case, transition, actor_id)

    def events(self, case_id: uuid.UUID) -> list[ReviewEventRead]:
        self.get(case_id)
        events = self.session.scalars(
            select(ReviewEvent)
            .where(ReviewEvent.review_case_id == case_id)
            .order_by(ReviewEvent.sequence_number)
        )
        return [review_event_to_read(event) for event in events]

    def verify_audit(self, case_id: uuid.UUID) -> AuditVerificationRead:
        case = self.get(case_id)
        events = list(
            self.session.scalars(
                select(ReviewEvent)
                .where(ReviewEvent.review_case_id == case_id)
                .order_by(ReviewEvent.sequence_number)
            )
        )
        errors: list[str] = []
        previous_hash: str | None = None
        reconstructed = ReconstructedState(None, None, None, None, 0)
        for expected_sequence, event in enumerate(events, start=1):
            if event.sequence_number != expected_sequence:
                errors.append(f"SEQUENCE_GAP_AT_{expected_sequence}")
            if event.previous_hash != previous_hash:
                errors.append(f"PREVIOUS_HASH_MISMATCH_AT_{event.sequence_number}")
            try:
                expected_hash = event_hash(
                    case_id=case.id,
                    sequence_number=event.sequence_number,
                    event_type=event.event_type,
                    actor_id=event.actor_id,
                    occurred_at=event.occurred_at,
                    payload=event.payload,
                    previous_hash=event.previous_hash,
                    hash_version=event.hash_version,
                )
                if event.event_hash != expected_hash:
                    errors.append(f"EVENT_HASH_MISMATCH_AT_{event.sequence_number}")
            except UnsupportedAuditHashVersionError:
                errors.append(f"UNSUPPORTED_HASH_VERSION_AT_{event.sequence_number}")
            try:
                reconstructed = _reconstruct_event(reconstructed, event)
            except (ValueError, KeyError):
                errors.append(f"INVALID_TRANSITION_AT_{event.sequence_number}")
            previous_hash = event.event_hash

        if (
            reconstructed.status != case.status
            or reconstructed.assignee != case.assigned_reviewer_id
            or reconstructed.resolution != case.resolution
            or reconstructed.resolution_reason != case.resolution_reason
            or reconstructed.version != case.version
        ):
            errors.append("MATERIALIZED_STATE_MISMATCH")
        return AuditVerificationRead(
            review_case_id=case.id,
            valid=not errors,
            event_count=len(events),
            last_sequence_number=events[-1].sequence_number if events else 0,
            errors=errors,
            reconstructed_status=reconstructed.status,
            reconstructed_assignee=reconstructed.assignee,
            reconstructed_resolution=reconstructed.resolution,
            reconstructed_resolution_reason=reconstructed.resolution_reason,
            reconstructed_version=reconstructed.version,
            reconstructed_opening_triggers=list(reconstructed.opening_triggers),
        )

    def reconcile(self) -> ReconciliationResult:
        runs = list(
            self.session.scalars(
                select(MatchRun)
                .where(MatchRun.decision == MatchDecision.NEEDS_REVIEW)
                .order_by(MatchRun.created_at, MatchRun.id)
            )
        )
        created = 0
        already_present = 0
        for run in runs:
            risk_assessment = self.session.scalar(
                select(RiskAssessment)
                .where(RiskAssessment.match_run_id == run.id)
                .options(selectinload(RiskAssessment.signals))
            )
            _, was_created = ensure_review_case(self.session, run, risk_assessment)
            created += int(was_created)
            already_present += int(not was_created)
        self.session.commit()
        return ReconciliationResult(len(runs), created, already_present)

    @staticmethod
    def _state(case: ReviewCase) -> ReviewState:
        return ReviewState(
            case.status,
            case.assigned_reviewer_id,
            case.version,
            case.resolution,
            case.resolution_reason,
        )

    def _apply(
        self, case: ReviewCase, transition: Transition, actor_id: str
    ) -> ReviewCase:
        occurred_at = _now()
        expected_version = case.version
        values: dict[str, object] = {
            "status": transition.status,
            "assigned_reviewer_id": transition.assignee,
            "version": expected_version + 1,
            "resolution": transition.resolution,
            "resolution_reason": transition.resolution_reason,
        }
        if transition.event_type == ReviewEventType.CASE_CLAIMED:
            values["claimed_at"] = occurred_at
        elif transition.event_type == ReviewEventType.CASE_RELEASED:
            values["claimed_at"] = None
        elif transition.event_type == ReviewEventType.CASE_RESOLVED:
            values["resolved_at"] = occurred_at

        result = self.session.execute(
            update(ReviewCase)
            .where(ReviewCase.id == case.id, ReviewCase.version == expected_version)
            .values(**values)
        )
        if getattr(result, "rowcount", 0) != 1:
            self.session.rollback()
            raise ReviewTransitionError("STALE_VERSION", "The review case version is stale")

        previous = self.session.scalar(
            select(ReviewEvent).where(
                ReviewEvent.review_case_id == case.id,
                ReviewEvent.sequence_number == expected_version,
            )
        )
        if previous is None:
            self.session.rollback()
            raise RuntimeError("Review event history is incomplete")
        sequence = expected_version + 1
        event = ReviewEvent(
            id=uuid.uuid4(),
            review_case_id=case.id,
            sequence_number=sequence,
            event_type=transition.event_type,
            actor_id=actor_id,
            payload=transition.payload,
            hash_version=AUDIT_HASH_V2,
            previous_hash=previous.event_hash,
            event_hash=event_hash(
                case_id=case.id,
                sequence_number=sequence,
                event_type=transition.event_type,
                actor_id=actor_id,
                occurred_at=occurred_at,
                payload=transition.payload,
                previous_hash=previous.event_hash,
                hash_version=AUDIT_HASH_V2,
            ),
            occurred_at=occurred_at,
        )
        self.session.add(event)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ReviewTransitionError(
                "STALE_VERSION", "The review case version is stale"
            ) from exc
        return self.get(case.id)


def _reconstruct_event(state: ReconstructedState, event: ReviewEvent) -> ReconstructedState:
    if event.event_type == ReviewEventType.CASE_OPENED:
        if state.version != 0 or event.actor_id != SYSTEM_ACTOR_ID:
            raise ValueError
    elif event.event_type == ReviewEventType.CASE_CLAIMED:
        if state.status != ReviewStatus.OPEN:
            raise ValueError
    elif event.event_type == ReviewEventType.COMMENT_ADDED:
        if state.status == ReviewStatus.RESOLVED or state.status is None:
            raise ValueError
    elif event.event_type in {ReviewEventType.CASE_RELEASED, ReviewEventType.CASE_RESOLVED}:
        if state.status != ReviewStatus.CLAIMED or state.assignee != event.actor_id:
            raise ValueError
    return apply_event(state, event.event_type, event.actor_id, event.payload)


def _encode_cursor(case: ReviewCase) -> str:
    raw = f"{case.opened_at.isoformat()}|{case.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        timestamp, identifier = raw.rsplit("|", 1)
        return datetime.fromisoformat(timestamp), uuid.UUID(identifier)
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise InvalidReviewCursorError("Invalid review queue cursor") from exc
