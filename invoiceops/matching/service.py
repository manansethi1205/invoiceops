import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from invoiceops.extraction.selection import current_successful_extraction
from invoiceops.matching.context import ThreeWayContextBuilder
from invoiceops.matching.engine import match_invoice
from invoiceops.matching.three_way import AllocationDraft, match_invoice_three_way
from invoiceops.models import (
    TWO_WAY_CONTEXT_FINGERPRINT,
    Document,
    ExtractionRun,
    MatchRun,
    PurchaseOrder,
    PurchaseOrderLine,
    ReviewCase,
    ThreeWayAllocation,
    ThreeWayContext,
)
from invoiceops.po_locking import lock_purchase_order
from invoiceops.review.service import ensure_review_case
from invoiceops.risk.service import DuplicateRiskService, select_effective_assessment
from invoiceops.schemas.extraction import Invoice
from invoiceops.schemas.matching import (
    MatchDecision,
    MatchingMode,
    MatchingPolicy,
    MatchResult,
    MatchRunRead,
    PurchaseOrderCreate,
    PurchaseOrderLineRead,
    PurchaseOrderRead,
    ThreeWayMatchingPolicy,
)
from invoiceops.schemas.risk import RiskDisposition


class DocumentNotFoundError(LookupError):
    pass


class PurchaseOrderNotFoundError(LookupError):
    pass


class MatchRunNotFoundError(LookupError):
    pass


class ExtractionNotReadyError(RuntimeError):
    pass


@dataclass(frozen=True)
class MatchServiceResult:
    run: MatchRun
    created: bool


def purchase_order_to_read(purchase_order: PurchaseOrder) -> PurchaseOrderRead:
    return PurchaseOrderRead(
        id=purchase_order.id,
        external_po_number=purchase_order.external_po_number,
        vendor_name=purchase_order.vendor_name,
        currency=purchase_order.currency,
        created_at=purchase_order.created_at,
        lines=[PurchaseOrderLineRead.model_validate(line) for line in purchase_order.lines],
    )


def match_run_to_read(run: MatchRun) -> MatchRunRead:
    risk = select_effective_assessment(run)
    policy = (
        ThreeWayMatchingPolicy.model_validate(run.policy_snapshot)
        if run.matching_mode == MatchingMode.THREE_WAY
        else MatchingPolicy.model_validate(run.policy_snapshot)
    )
    return MatchRunRead(
        id=run.id,
        document_id=run.document_id,
        purchase_order_id=run.purchase_order_id,
        extraction_run_id=run.extraction_run_id,
        policy_version=run.policy_version,
        policy_snapshot=policy,
        matching_mode=run.matching_mode,
        context_fingerprint=(
            run.matching_context_fingerprint
            if run.matching_mode == MatchingMode.THREE_WAY
            else None
        ),
        three_way_context_url=(
            f"/v1/matches/{run.id}/three-way-context"
            if run.matching_mode == MatchingMode.THREE_WAY
            else None
        ),
        decision=run.decision,
        result=MatchResult.model_validate(run.result_json),
        risk_assessment_id=risk.id if risk is not None else None,
        risk_disposition=risk.disposition if risk is not None else None,
        risk_url=f"/v1/matches/{run.id}/risk" if risk is not None else None,
        review_case_id=run.review_case.id if run.review_case is not None else None,
        review_status=run.review_case.status.value if run.review_case is not None else None,
        human_resolution=(
            run.review_case.resolution.value
            if run.review_case is not None and run.review_case.resolution is not None
            else None
        ),
        payment_authorized=False,
        created_at=run.created_at,
    )


class PurchaseOrderService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, command: PurchaseOrderCreate) -> PurchaseOrder:
        purchase_order = PurchaseOrder(
            external_po_number=command.external_po_number,
            vendor_name=command.vendor_name,
            currency=command.currency,
            lines=[
                PurchaseOrderLine(
                    line_number=line.line_number,
                    description=line.description,
                    ordered_quantity=line.ordered_quantity,
                    unit_price=line.unit_price,
                )
                for line in command.lines
            ],
        )
        self.session.add(purchase_order)
        self.session.commit()
        self.session.expire_all()
        return self.get(purchase_order.id)

    def get(self, purchase_order_id: uuid.UUID) -> PurchaseOrder:
        purchase_order = self.session.scalar(
            select(PurchaseOrder)
            .where(PurchaseOrder.id == purchase_order_id)
            .options(selectinload(PurchaseOrder.lines))
        )
        if purchase_order is None:
            raise PurchaseOrderNotFoundError
        return purchase_order


class MatchingService:
    def __init__(
        self,
        session: Session,
        policy: MatchingPolicy | None = None,
        three_way_policy: ThreeWayMatchingPolicy | None = None,
    ) -> None:
        self.session = session
        self.policy = policy or MatchingPolicy()
        self.three_way_policy = three_way_policy or ThreeWayMatchingPolicy()

    def match(
        self,
        document_id: uuid.UUID,
        purchase_order_id: uuid.UUID,
        mode: MatchingMode = MatchingMode.TWO_WAY,
    ) -> MatchServiceResult:
        if self.session.get(Document, document_id) is None:
            raise DocumentNotFoundError
        purchase_order = self._locked_purchase_order(purchase_order_id, mode)
        extraction_run = self._latest_successful_extraction(document_id)
        if extraction_run.output_json is None:
            raise ExtractionNotReadyError
        invoice = Invoice.model_validate(extraction_run.output_json)
        policy_version = (
            self.three_way_policy.version if mode == MatchingMode.THREE_WAY else self.policy.version
        )
        snapshot = None
        if mode == MatchingMode.THREE_WAY:
            builder = ThreeWayContextBuilder(self.session)
            for prior in self._find_prior_candidates(
                document_id, purchase_order_id, extraction_run.id, mode, policy_version
            ):
                _, retry_fingerprint = builder.build(
                    purchase_order,
                    self.three_way_policy,
                    exclude_document_id=document_id,
                )
                if retry_fingerprint == prior.matching_context_fingerprint:
                    self._ensure_case_for_existing(prior)
                    return MatchServiceResult(prior, created=False)
            snapshot, context_fingerprint = builder.build(
                purchase_order,
                self.three_way_policy,
                exclude_document_id=document_id,
            )
        else:
            context_fingerprint = TWO_WAY_CONTEXT_FINGERPRINT
        existing = self._find_existing(
            document_id,
            purchase_order_id,
            extraction_run.id,
            mode,
            policy_version,
            context_fingerprint,
        )
        if existing is not None:
            self._ensure_case_for_existing(existing)
            return MatchServiceResult(existing, created=False)

        if mode == MatchingMode.THREE_WAY:
            assert snapshot is not None
            result, allocations = match_invoice_three_way(
                invoice,
                purchase_order_to_read(purchase_order),
                snapshot,
                self.three_way_policy,
            )
            policy_snapshot = self.three_way_policy.model_dump(mode="json")
        else:
            result = match_invoice(invoice, purchase_order_to_read(purchase_order), self.policy)
            allocations = []
            policy_snapshot = self.policy.model_dump(mode="json")
        run = MatchRun(
            document_id=document_id,
            purchase_order_id=purchase_order_id,
            extraction_run_id=extraction_run.id,
            policy_version=policy_version,
            policy_snapshot=policy_snapshot,
            matching_mode=mode,
            matching_context_fingerprint=context_fingerprint,
            risk_policy_version="duplicate-risk-v1",
            decision=result.decision,
            result_json=result.model_dump(mode="json"),
        )
        self.session.add(run)
        try:
            self.session.flush()
            if snapshot is not None:
                self.session.add(
                    ThreeWayContext(
                        match_run_id=run.id,
                        context_fingerprint=context_fingerprint,
                        snapshot=snapshot.model_dump(mode="json"),
                    )
                )
                self.session.add_all(
                    ThreeWayAllocation(
                        match_run_id=run.id,
                        document_id=document_id,
                        purchase_order_line_id=item.purchase_order_line_id,
                        invoice_line_index=item.invoice_line_index,
                        allocated_quantity=item.quantity,
                    )
                    for item in self._new_allocations(document_id, allocations)
                )
            risk = DuplicateRiskService(self.session).ensure(run, purchase_order, invoice)
            ensure_review_case(self.session, run, risk.assessment)
            self.session.commit()
            self.session.refresh(run)
            return MatchServiceResult(run, created=True)
        except IntegrityError:
            self.session.rollback()
            concurrent = self._find_existing(
                document_id,
                purchase_order_id,
                extraction_run.id,
                mode,
                policy_version,
                context_fingerprint,
            )
            if concurrent is None:
                raise
            self._ensure_case_for_existing(concurrent)
            return MatchServiceResult(concurrent, created=False)

    def get(self, match_run_id: uuid.UUID) -> MatchRun:
        run = self.session.get(MatchRun, match_run_id)
        if run is None:
            raise MatchRunNotFoundError
        return run

    def _latest_successful_extraction(self, document_id: uuid.UUID) -> ExtractionRun:
        run = current_successful_extraction(self.session, document_id)
        if run is None:
            raise ExtractionNotReadyError
        return run

    def _find_existing(
        self,
        document_id: uuid.UUID,
        purchase_order_id: uuid.UUID,
        extraction_run_id: uuid.UUID,
        mode: MatchingMode,
        policy_version: str,
        context_fingerprint: str,
    ) -> MatchRun | None:
        return self.session.scalar(
            select(MatchRun).where(
                MatchRun.document_id == document_id,
                MatchRun.purchase_order_id == purchase_order_id,
                MatchRun.extraction_run_id == extraction_run_id,
                MatchRun.policy_version == policy_version,
                MatchRun.matching_mode == mode,
                MatchRun.matching_context_fingerprint == context_fingerprint,
            )
        )

    def _find_prior_candidates(
        self,
        document_id: uuid.UUID,
        purchase_order_id: uuid.UUID,
        extraction_run_id: uuid.UUID,
        mode: MatchingMode,
        policy_version: str,
    ) -> list[MatchRun]:
        return list(
            self.session.scalars(
                select(MatchRun)
                .where(
                    MatchRun.document_id == document_id,
                    MatchRun.purchase_order_id == purchase_order_id,
                    MatchRun.extraction_run_id == extraction_run_id,
                    MatchRun.matching_mode == mode,
                    MatchRun.policy_version == policy_version,
                )
                .order_by(MatchRun.created_at.desc(), MatchRun.id.desc())
            )
        )

    def _locked_purchase_order(
        self, purchase_order_id: uuid.UUID, mode: MatchingMode
    ) -> PurchaseOrder:
        if mode == MatchingMode.THREE_WAY:
            purchase_order = lock_purchase_order(
                self.session, purchase_order_id, include_lines=True
            )
        else:
            purchase_order = self.session.scalar(
                select(PurchaseOrder)
                .where(PurchaseOrder.id == purchase_order_id)
                .options(selectinload(PurchaseOrder.lines))
            )
        if purchase_order is None:
            raise PurchaseOrderNotFoundError
        return purchase_order

    def _new_allocations(
        self,
        document_id: uuid.UUID,
        allocations: list[AllocationDraft],
    ) -> list[AllocationDraft]:
        existing = set(
            self.session.scalars(
                select(ThreeWayAllocation.invoice_line_index).where(
                    ThreeWayAllocation.document_id == document_id
                )
            )
        )
        return [item for item in allocations if item.invoice_line_index not in existing]

    def _ensure_case_for_existing(self, run: MatchRun) -> None:
        try:
            extraction = self.session.get(ExtractionRun, run.extraction_run_id)
            purchase_order = self.session.get(PurchaseOrder, run.purchase_order_id)
            if extraction is None or extraction.output_json is None or purchase_order is None:
                raise ExtractionNotReadyError
            invoice = Invoice.model_validate(extraction.output_json)
            risk = DuplicateRiskService(self.session).ensure(run, purchase_order, invoice)
            ensure_review_case(self.session, run, risk.assessment)
            self.session.commit()
        except IntegrityError:
            # Another retry repaired the same historical run first.
            self.session.rollback()
            assessment = DuplicateRiskService(self.session).get_for_match(run.id)
            case = self.session.scalar(select(ReviewCase).where(ReviewCase.match_run_id == run.id))
            requires_case = run.decision == MatchDecision.NEEDS_REVIEW or (
                assessment.disposition == RiskDisposition.NEEDS_REVIEW
            )
            if requires_case and case is None:
                raise
