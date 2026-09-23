import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from invoiceops.extraction.selection import current_successful_extraction
from invoiceops.matching.engine import match_invoice
from invoiceops.models import (
    Document,
    ExtractionRun,
    MatchRun,
    PurchaseOrder,
    PurchaseOrderLine,
    ReviewCase,
)
from invoiceops.review.service import ensure_review_case
from invoiceops.schemas.extraction import Invoice
from invoiceops.schemas.matching import (
    MatchingPolicy,
    MatchResult,
    MatchRunRead,
    PurchaseOrderCreate,
    PurchaseOrderLineRead,
    PurchaseOrderRead,
)


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
    return MatchRunRead(
        id=run.id,
        document_id=run.document_id,
        purchase_order_id=run.purchase_order_id,
        extraction_run_id=run.extraction_run_id,
        policy_version=run.policy_version,
        policy_snapshot=MatchingPolicy.model_validate(run.policy_snapshot),
        decision=run.decision,
        result=MatchResult.model_validate(run.result_json),
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
    def __init__(self, session: Session, policy: MatchingPolicy | None = None) -> None:
        self.session = session
        self.policy = policy or MatchingPolicy()

    def match(
        self, document_id: uuid.UUID, purchase_order_id: uuid.UUID
    ) -> MatchServiceResult:
        if self.session.get(Document, document_id) is None:
            raise DocumentNotFoundError
        purchase_order = PurchaseOrderService(self.session).get(purchase_order_id)
        extraction_run = self._latest_successful_extraction(document_id)
        existing = self._find_existing(document_id, purchase_order_id, extraction_run.id)
        if existing is not None:
            self._ensure_case_for_existing(existing)
            return MatchServiceResult(existing, created=False)

        if extraction_run.output_json is None:
            raise ExtractionNotReadyError
        invoice = Invoice.model_validate(extraction_run.output_json)
        result = match_invoice(invoice, purchase_order_to_read(purchase_order), self.policy)
        run = MatchRun(
            document_id=document_id,
            purchase_order_id=purchase_order_id,
            extraction_run_id=extraction_run.id,
            policy_version=self.policy.version,
            policy_snapshot=self.policy.model_dump(mode="json"),
            decision=result.decision,
            result_json=result.model_dump(mode="json"),
        )
        self.session.add(run)
        try:
            self.session.flush()
            ensure_review_case(self.session, run)
            self.session.commit()
            self.session.refresh(run)
            return MatchServiceResult(run, created=True)
        except IntegrityError:
            self.session.rollback()
            concurrent = self._find_existing(
                document_id, purchase_order_id, extraction_run.id
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
    ) -> MatchRun | None:
        return self.session.scalar(
            select(MatchRun).where(
                MatchRun.document_id == document_id,
                MatchRun.purchase_order_id == purchase_order_id,
                MatchRun.extraction_run_id == extraction_run_id,
                MatchRun.policy_version == self.policy.version,
            )
        )

    def _ensure_case_for_existing(self, run: MatchRun) -> None:
        try:
            ensure_review_case(self.session, run)
            self.session.commit()
        except IntegrityError:
            # Another retry repaired the same historical run first.
            self.session.rollback()
            if self.session.scalar(
                select(ReviewCase).where(ReviewCase.match_run_id == run.id)
            ) is None:
                raise
