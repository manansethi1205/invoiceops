import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, selectinload

from invoiceops.cases.events import append_case_event
from invoiceops.extraction.selection import current_successful_extraction
from invoiceops.ingestion.dispatch import JobDispatcher
from invoiceops.ingestion.service import IngestionService, UploadCommand
from invoiceops.ingestion.storage import ObjectStore
from invoiceops.matching.service import MatchingService
from invoiceops.models import (
    CaseConfirmation,
    CaseDocument,
    CaseMatchContext,
    Document,
    ExtractionRunStatus,
    GoodsReceipt,
    GoodsReceiptLine,
    JobStatus,
    MatchRun,
    PayableCase,
    PurchaseOrder,
    PurchaseOrderLine,
    SupportingExtractionRun,
)
from invoiceops.observability.metrics import metrics
from invoiceops.receipts.service import receipt_request_fingerprint
from invoiceops.schemas.cases import (
    CaseAttachmentAccepted,
    CaseCreate,
    CaseDocumentRead,
    CaseMatchCommand,
    CaseRead,
    CaseStatus,
    ConfirmationRead,
    ConfirmationStatus,
    DocumentRole,
    ExtractedGoodsReceipt,
    ExtractedPurchaseOrder,
    PurchaseOrderConfirmation,
    ReceiptConfirmation,
    SupportingExtractionStatus,
)
from invoiceops.schemas.matching import MatchDecision, MatchingMode
from invoiceops.schemas.receipts import GoodsReceiptCreate, GoodsReceiptLineCreate


class CaseNotFoundError(LookupError):
    pass


class CaseConflictError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CaseNotReadyError(RuntimeError):
    pass


@dataclass(frozen=True)
class CaseCreateResult:
    payable_case: PayableCase
    created: bool


def _fingerprint(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def case_to_read(payable_case: PayableCase) -> CaseRead:
    return CaseRead.model_validate(payable_case, from_attributes=True)


def _supporting_run_for(
    session: Session, attachment: CaseDocument
) -> SupportingExtractionRun | None:
    return session.scalar(
        select(SupportingExtractionRun)
        .where(
            SupportingExtractionRun.document_id == attachment.document_id,
            SupportingExtractionRun.role == attachment.role,
        )
        .order_by(SupportingExtractionRun.created_at.desc())
        .limit(1)
    )


def attachment_to_read(session: Session, attachment: CaseDocument) -> CaseDocumentRead:
    run = _supporting_run_for(session, attachment)
    confirmation = session.scalar(
        select(CaseConfirmation).where(CaseConfirmation.case_document_id == attachment.id)
    )
    if attachment.role == DocumentRole.INVOICE:
        confirmation_status = ConfirmationStatus.NOT_REQUIRED
    else:
        confirmation_status = (
            ConfirmationStatus.CONFIRMED if confirmation is not None else ConfirmationStatus.PENDING
        )
    return CaseDocumentRead(
        id=attachment.id,
        case_id=attachment.case_id,
        document_id=attachment.document_id,
        job_id=attachment.document.job.id,
        role=attachment.role,
        filename=attachment.document.original_filename,
        content_type=attachment.document.content_type,
        byte_size=attachment.document.byte_size,
        attachment_order=attachment.attachment_order,
        supersedes_id=attachment.supersedes_id,
        is_active=attachment.active_slot is not None
        or (
            attachment.role
            in {
                DocumentRole.GOODS_RECEIPT,
                DocumentRole.DELIVERY_NOTE,
            }
            and not session.scalar(
                select(
                    exists().where(CaseDocument.supersedes_id == attachment.id)
                )
            )
        ),
        job_status=(
            run.status.value.lower()
            if run is not None and attachment.role != DocumentRole.INVOICE
            else attachment.document.job.status.value
        ),
        extraction_status=run.status if run is not None else None,
        confirmation_status=confirmation_status,
        created_at=attachment.created_at,
    )


class PayableCaseService:
    def __init__(
        self,
        session: Session,
        object_store: ObjectStore | None = None,
        dispatcher: JobDispatcher | None = None,
        max_upload_bytes: int = 15 * 1024 * 1024,
    ) -> None:
        self.session = session
        self.object_store = object_store
        self.dispatcher = dispatcher
        self.max_upload_bytes = max_upload_bytes

    def create(self, command: CaseCreate) -> CaseCreateResult:
        fingerprint = _fingerprint({"operation": "create_case"})
        existing = self.session.scalar(
            select(PayableCase).where(PayableCase.idempotency_key == command.idempotency_key)
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise CaseConflictError("IDEMPOTENCY_KEY_REUSED", "Idempotency key payload differs")
            metrics.add("case_events", "case", event="REPLAYED")
            return CaseCreateResult(existing, False)
        case_id = uuid.uuid4()
        payable_case = PayableCase(
            id=case_id,
            case_number=f"CASE-{datetime.now(UTC):%Y%m%d}-{case_id.hex[:8].upper()}",
            status=CaseStatus.DRAFT,
            version=1,
            idempotency_key=command.idempotency_key,
            request_fingerprint=fingerprint,
        )
        self.session.add(payable_case)
        try:
            self.session.flush()
            append_case_event(
                self.session,
                case_id=payable_case.id,
                event_key="case.created",
                event_type="CASE_CREATED",
                stage="case",
                status="completed",
                message="Payable case created",
            )
            self.session.commit()
            metrics.add("case_events", "case", event="CREATED")
            return CaseCreateResult(payable_case, True)
        except IntegrityError:
            self.session.rollback()
            concurrent = self.session.scalar(
                select(PayableCase).where(PayableCase.idempotency_key == command.idempotency_key)
            )
            if concurrent is None or concurrent.request_fingerprint != fingerprint:
                raise CaseConflictError(
                    "IDEMPOTENCY_KEY_REUSED", "Idempotency key payload differs"
                ) from None
            return CaseCreateResult(concurrent, False)

    def get(self, case_id: uuid.UUID, *, lock: bool = False) -> PayableCase:
        statement = select(PayableCase).where(PayableCase.id == case_id)
        if lock:
            statement = statement.with_for_update()
        payable_case = self.session.scalar(statement)
        if payable_case is None:
            raise CaseNotFoundError
        return payable_case

    def list_documents(self, case_id: uuid.UUID) -> list[CaseDocument]:
        self.get(case_id)
        return list(
            self.session.scalars(
                select(CaseDocument)
                .where(CaseDocument.case_id == case_id)
                .options(selectinload(CaseDocument.document).selectinload(Document.job))
                .order_by(CaseDocument.attachment_order)
            )
        )

    def attach(
        self,
        case_id: uuid.UUID,
        *,
        role: DocumentRole,
        idempotency_key: str,
        expected_case_version: int,
        command: UploadCommand,
        supersedes_id: uuid.UUID | None = None,
    ) -> CaseAttachmentAccepted:
        if self.object_store is None or self.dispatcher is None:
            raise RuntimeError("attachment dependencies are not configured")
        digest = hashlib.sha256(command.body).hexdigest()
        fingerprint = _fingerprint(
            {
                "role": role.value,
                "sha256": digest,
                "supersedes_id": str(supersedes_id) if supersedes_id else None,
            }
        )
        replay = self.session.scalar(
            select(CaseDocument).where(
                CaseDocument.case_id == case_id,
                CaseDocument.idempotency_key == idempotency_key,
            )
        )
        if replay is not None:
            if replay.request_fingerprint != fingerprint:
                raise CaseConflictError("IDEMPOTENCY_KEY_REUSED", "Idempotency key payload differs")
            self._redispatch(replay)
            metrics.add(
                "case_attachments", "case_attachment", role=role.value, outcome="REPLAYED"
            )
            return CaseAttachmentAccepted(
                case=case_to_read(self.get(case_id)),
                attachment=attachment_to_read(self.session, replay),
                deduplicated_document=True,
                replayed=True,
            )
        initial_case = self.get(case_id)
        if initial_case.version != expected_case_version:
            raise CaseConflictError("STALE_CASE_VERSION", "Case version is stale")
        ingestion = IngestionService(
            self.session, self.object_store, self.dispatcher, self.max_upload_bytes
        ).ingest(command, dispatch=False)
        payable_case = self.get(case_id, lock=True)
        if payable_case.version != expected_case_version:
            raise CaseConflictError("STALE_CASE_VERSION", "Case version changed during upload")
        document = self.session.get(Document, ingestion.job.document_id)
        if document is None:
            raise RuntimeError("ingested document disappeared")
        existing_same = self.session.scalar(
            select(CaseDocument).where(
                CaseDocument.case_id == case_id,
                CaseDocument.role == role,
                CaseDocument.document_id == document.id,
            )
        )
        if existing_same is not None:
            raise CaseConflictError(
                "DOCUMENT_ALREADY_ATTACHED", "Document is already attached in this role"
            )
        active_slot = (
            role.value if role in {DocumentRole.INVOICE, DocumentRole.PURCHASE_ORDER} else None
        )
        if active_slot is not None:
            active = self.session.scalar(
                select(CaseDocument).where(
                    CaseDocument.case_id == case_id,
                    CaseDocument.active_slot == active_slot,
                )
            )
            if active is not None:
                if supersedes_id != active.id:
                    raise CaseConflictError(
                        "ACTIVE_DOCUMENT_EXISTS",
                        "Replace the active document by supplying its attachment id",
                    )
                active.active_slot = None
            elif supersedes_id is not None:
                raise CaseConflictError(
                    "INVALID_SUPERSESSION", "Superseded attachment is not active"
                )
        elif supersedes_id is not None:
            superseded = self.session.get(CaseDocument, supersedes_id)
            if (
                superseded is None
                or superseded.case_id != case_id
                or superseded.role != role
                or self._has_successor(superseded.id)
            ):
                raise CaseConflictError(
                    "INVALID_SUPERSESSION",
                    "Superseded receipt or delivery attachment is not active",
                )
        order = (
            int(
                self.session.scalar(
                    select(func.max(CaseDocument.attachment_order)).where(
                        CaseDocument.case_id == case_id
                    )
                )
                or 0
            )
            + 1
        )
        attachment = CaseDocument(
            case_id=case_id,
            document_id=document.id,
            role=role,
            attachment_order=order,
            active_slot=active_slot,
            supersedes_id=supersedes_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        self.session.add(attachment)
        payable_case.version += 1
        invoice_already_extracted = (
            role == DocumentRole.INVOICE
            and ingestion.job.status == JobStatus.SUCCEEDED
            and current_successful_extraction(self.session, document.id) is not None
        )
        payable_case.status = (
            CaseStatus.NEEDS_CONFIRMATION
            if invoice_already_extracted
            else CaseStatus.PROCESSING
        )
        try:
            self.session.flush()
            append_case_event(
                self.session,
                case_id=case_id,
                event_key=f"document.attached:{attachment.id}",
                event_type="UPLOAD_ACCEPTED",
                stage="upload",
                status="completed",
                message="Case document attached",
                document_id=document.id,
                document_role=role,
                payload={
                    "attachment_id": str(attachment.id),
                    "filename": document.original_filename,
                },
            )
            if invoice_already_extracted:
                invoice_run = current_successful_extraction(self.session, document.id)
                assert invoice_run is not None
                append_case_event(
                    self.session,
                    case_id=case_id,
                    event_key=f"invoice-extraction-completed:{invoice_run.id}",
                    event_type="EXTRACTION_COMPLETED",
                    stage="extraction",
                    status="completed",
                    message="Existing invoice extraction reused",
                    document_id=document.id,
                    document_role=role,
                    payload={"extraction_run_id": str(invoice_run.id), "reused": True},
                )
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self.session.scalar(
                select(CaseDocument).where(
                    CaseDocument.case_id == case_id,
                    CaseDocument.idempotency_key == idempotency_key,
                )
            )
            if concurrent is None or concurrent.request_fingerprint != fingerprint:
                raise CaseConflictError("ATTACHMENT_CONFLICT", "Attachment conflicted") from None
            self._redispatch(concurrent)
            metrics.add(
                "case_attachments", "case_attachment", role=role.value, outcome="REPLAYED"
            )
            return CaseAttachmentAccepted(
                case=case_to_read(self.get(case_id)),
                attachment=attachment_to_read(self.session, concurrent),
                deduplicated_document=not ingestion.created,
                replayed=True,
            )
        if role == DocumentRole.INVOICE and not invoice_already_extracted:
            try:
                self.dispatcher.enqueue(str(ingestion.job.id))
            except Exception:
                # The durable attachment remains PROCESSING and can be retried safely.
                pass
        elif role != DocumentRole.INVOICE:
            try:
                self.dispatcher.enqueue_supporting(str(attachment.id))
            except Exception:
                # The durable attachment remains PROCESSING and can be retried safely.
                pass
        self.session.refresh(payable_case)
        metrics.add(
            "case_attachments",
            "case_attachment",
            role=role.value,
            outcome="DEDUPLICATED" if not ingestion.created else "ATTACHED",
        )
        return CaseAttachmentAccepted(
            case=case_to_read(payable_case),
            attachment=attachment_to_read(self.session, attachment),
            deduplicated_document=not ingestion.created,
            replayed=False,
        )

    def _redispatch(self, attachment: CaseDocument) -> None:
        if self.dispatcher is None:
            return
        try:
            if attachment.role == DocumentRole.INVOICE:
                if attachment.document.job.status != JobStatus.SUCCEEDED:
                    self.dispatcher.enqueue(str(attachment.document.job.id))
            else:
                run = _supporting_run_for(self.session, attachment)
                if run is None or run.status != SupportingExtractionStatus.SUCCEEDED:
                    self.dispatcher.enqueue_supporting(str(attachment.id))
        except Exception:
            # The idempotent mutation remains retryable; dispatch errors do not duplicate data.
            return

    def confirm_purchase_order(
        self, case_id: uuid.UUID, command: PurchaseOrderConfirmation
    ) -> ConfirmationRead:
        attachment = self._active_attachment(case_id, DocumentRole.PURCHASE_ORDER)
        return self._confirm_po(case_id, attachment, command)

    def confirm_receipt(
        self,
        case_id: uuid.UUID,
        document_id: uuid.UUID,
        command: ReceiptConfirmation,
    ) -> ConfirmationRead:
        attachment = self.session.scalar(
            select(CaseDocument).where(
                CaseDocument.case_id == case_id,
                CaseDocument.document_id == document_id,
                CaseDocument.role.in_((DocumentRole.GOODS_RECEIPT, DocumentRole.DELIVERY_NOTE)),
            )
        )
        if attachment is None:
            raise CaseNotFoundError
        if self._has_successor(attachment.id):
            raise CaseConflictError(
                "ATTACHMENT_SUPERSEDED", "A superseded receipt cannot be confirmed"
            )
        return self._confirm_receipt(case_id, attachment, command)

    def match(self, case_id: uuid.UUID, command: CaseMatchCommand) -> MatchRun:
        replay = self.session.scalar(
            select(CaseMatchContext).where(
                CaseMatchContext.case_id == case_id,
                CaseMatchContext.idempotency_key == command.idempotency_key,
            )
        )
        if replay is not None:
            run = self.session.get(MatchRun, replay.match_run_id)
            if run is None:
                raise RuntimeError("case match context is corrupt")
            return run
        payable_case = self.get(case_id, lock=True)
        if payable_case.version != command.expected_case_version:
            raise CaseConflictError("STALE_CASE_VERSION", "Case version is stale")
        invoice_attachment = self._active_attachment(case_id, DocumentRole.INVOICE)
        po_attachment = self._active_attachment(case_id, DocumentRole.PURCHASE_ORDER)
        invoice_run = current_successful_extraction(self.session, invoice_attachment.document_id)
        po_confirmation = self._confirmation(po_attachment.id)
        if invoice_run is None or invoice_run.status != ExtractionRunStatus.SUCCEEDED:
            raise CaseNotReadyError("Invoice extraction is not ready")
        if po_confirmation is None:
            raise CaseNotReadyError("Purchase order is not confirmed")
        receipt_successor = aliased(CaseDocument)
        receipt_confirmations = list(
            self.session.scalars(
                select(CaseConfirmation)
                .join(CaseDocument, CaseDocument.id == CaseConfirmation.case_document_id)
                .where(
                    CaseDocument.case_id == case_id,
                    CaseDocument.role.in_((DocumentRole.GOODS_RECEIPT, DocumentRole.DELIVERY_NOTE)),
                    CaseConfirmation.canonical_record_type == "GOODS_RECEIPT",
                    ~exists().where(receipt_successor.supersedes_id == CaseDocument.id),
                )
                .order_by(CaseConfirmation.created_at, CaseConfirmation.id)
            )
        )
        matching_mode = (
            MatchingMode.THREE_WAY if receipt_confirmations else MatchingMode.TWO_WAY
        )
        matching_service = MatchingService(self.session)
        matching_policy_version = (
            matching_service.three_way_policy.version
            if matching_mode == MatchingMode.THREE_WAY
            else matching_service.policy.version
        )
        context = {
            "matching_mode": matching_mode.value,
            "matching_policy_version": matching_policy_version,
            "invoice_attachment_id": str(invoice_attachment.id),
            "invoice_document_id": str(invoice_attachment.document_id),
            "invoice_extraction_run_id": str(invoice_run.id),
            "purchase_order_attachment_id": str(po_attachment.id),
            "purchase_order_confirmation_id": str(po_confirmation.id),
            "purchase_order_id": str(po_confirmation.canonical_record_id),
            "receipt_confirmation_ids": [str(item.id) for item in receipt_confirmations],
            "receipt_ids": [str(item.canonical_record_id) for item in receipt_confirmations],
        }
        fingerprint = _fingerprint(context)
        context_replay = self.session.scalar(
            select(CaseMatchContext).where(
                CaseMatchContext.case_id == case_id,
                CaseMatchContext.request_fingerprint == fingerprint,
            )
        )
        if context_replay is not None:
            run = self.session.get(MatchRun, context_replay.match_run_id)
            if run is None:
                raise RuntimeError("case match context is corrupt")
            return run
        result = matching_service.match(
            invoice_attachment.document_id,
            po_confirmation.canonical_record_id,
            matching_mode,
        )
        payable_case = self.get(case_id, lock=True)
        self.session.add(
            CaseMatchContext(
                case_id=case_id,
                match_run_id=result.run.id,
                context_json=context,
                idempotency_key=command.idempotency_key,
                request_fingerprint=fingerprint,
            )
        )
        payable_case.version += 1
        payable_case.status = (
            CaseStatus.MATCHED
            if result.run.decision == MatchDecision.MATCHED and result.run.review_case is None
            else CaseStatus.NEEDS_REVIEW
        )
        append_case_event(
            self.session,
            case_id=case_id,
            event_key=f"case.matched:{fingerprint}",
            event_type="CASE_MATCHED",
            stage="matching",
            status="completed",
            message="Deterministic case matching completed",
            payload={"match_run_id": str(result.run.id), "decision": result.run.decision.value},
        )
        self.session.commit()
        return result.run

    def _active_attachment(self, case_id: uuid.UUID, role: DocumentRole) -> CaseDocument:
        attachment = self.session.scalar(
            select(CaseDocument).where(
                CaseDocument.case_id == case_id,
                CaseDocument.active_slot == role.value,
            )
        )
        if attachment is None:
            raise CaseNotReadyError(f"Active {role.value} document is required")
        return attachment

    def _confirmation(self, attachment_id: uuid.UUID) -> CaseConfirmation | None:
        return self.session.scalar(
            select(CaseConfirmation).where(CaseConfirmation.case_document_id == attachment_id)
        )

    def _has_successor(self, attachment_id: uuid.UUID) -> bool:
        return bool(
            self.session.scalar(
                select(exists().where(CaseDocument.supersedes_id == attachment_id))
            )
        )

    def _support_run(
        self, attachment: CaseDocument, run_id: uuid.UUID, version: str
    ) -> SupportingExtractionRun:
        run = self.session.get(SupportingExtractionRun, run_id)
        if (
            run is None
            or run.document_id != attachment.document_id
            or run.role != attachment.role
            or run.extractor_version != version
            or run.status != SupportingExtractionStatus.SUCCEEDED
            or run.output_json is None
        ):
            raise CaseNotReadyError("Supporting extraction run is not confirmable")
        return run

    def _confirm_po(
        self,
        case_id: uuid.UUID,
        attachment: CaseDocument,
        command: PurchaseOrderConfirmation,
    ) -> ConfirmationRead:
        payload = command.confirmed.model_dump(mode="json")
        fingerprint = _fingerprint({"attachment_id": str(attachment.id), "confirmed": payload})
        replay = self._confirmation_replay(case_id, command.idempotency_key, fingerprint)
        if replay is not None:
            return ConfirmationRead.model_validate(replay, from_attributes=True)
        payable_case = self.get(case_id, lock=True)
        if payable_case.version != command.expected_case_version:
            raise CaseConflictError("STALE_CASE_VERSION", "Case version is stale")
        run = self._support_run(attachment, command.extraction_run_id, command.extractor_version)
        extracted = ExtractedPurchaseOrder.model_validate(run.output_json)
        corrected = self._po_corrected_fields(
            extracted,
            payload,
            amount_provided=[
                "line_total" in line.model_fields_set for line in command.confirmed.lines
            ],
        )
        if corrected and not command.correction_reason:
            raise CaseConflictError(
                "CORRECTION_REASON_REQUIRED", "Corrected values require a reason"
            )
        canonical = PurchaseOrder(
            external_po_number=command.confirmed.external_po_number,
            vendor_name=command.confirmed.vendor_name,
            currency=command.confirmed.currency,
            lines=[
                PurchaseOrderLine(
                    line_number=item.line_number,
                    description=item.description,
                    ordered_quantity=item.ordered_quantity,
                    unit_price=item.unit_price,
                    line_total=item.line_total,
                )
                for item in command.confirmed.lines
            ],
        )
        self.session.add(canonical)
        self.session.flush()
        confirmation = CaseConfirmation(
            case_id=case_id,
            case_document_id=attachment.id,
            extraction_run_id=run.id,
            extractor_version=run.extractor_version,
            canonical_record_type="PURCHASE_ORDER",
            canonical_record_id=canonical.id,
            confirmed_json=payload,
            corrected_fields=corrected,
            correction_reason=command.correction_reason,
            idempotency_key=command.idempotency_key,
            request_fingerprint=fingerprint,
        )
        self.session.add(confirmation)
        payable_case.version += 1
        payable_case.status = self._status_after_confirmation(case_id, attachment.id)
        self._confirmation_event(confirmation, attachment, corrected)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self._confirmation_replay(case_id, command.idempotency_key, fingerprint)
            if concurrent is None:
                raise CaseConflictError(
                    "ATTACHMENT_ALREADY_CONFIRMED",
                    "This attachment already has a confirmation",
                ) from None
            confirmation = concurrent
        self._observe_confirmation(attachment, corrected, payable_case)
        return ConfirmationRead.model_validate(confirmation, from_attributes=True)

    def _confirm_receipt(
        self,
        case_id: uuid.UUID,
        attachment: CaseDocument,
        command: ReceiptConfirmation,
    ) -> ConfirmationRead:
        payload = command.confirmed.model_dump(mode="json")
        fingerprint = _fingerprint({"attachment_id": str(attachment.id), "confirmed": payload})
        replay = self._confirmation_replay(case_id, command.idempotency_key, fingerprint)
        if replay is not None:
            return ConfirmationRead.model_validate(replay, from_attributes=True)
        payable_case = self.get(case_id, lock=True)
        if payable_case.version != command.expected_case_version:
            raise CaseConflictError("STALE_CASE_VERSION", "Case version is stale")
        run = self._support_run(attachment, command.extraction_run_id, command.extractor_version)
        extracted = ExtractedGoodsReceipt.model_validate(run.output_json)
        corrected = self._receipt_corrected_fields(extracted, payload)
        if corrected and not command.correction_reason:
            raise CaseConflictError(
                "CORRECTION_REASON_REQUIRED", "Corrected values require a reason"
            )
        po_attachment = self._active_attachment(case_id, DocumentRole.PURCHASE_ORDER)
        po_confirmation = self._confirmation(po_attachment.id)
        if po_confirmation is None:
            raise CaseNotReadyError("Purchase order must be confirmed first")
        purchase_order = self.session.scalar(
            select(PurchaseOrder)
            .where(PurchaseOrder.id == po_confirmation.canonical_record_id)
            .options(selectinload(PurchaseOrder.lines))
        )
        if purchase_order is None:
            raise RuntimeError("confirmed purchase order is missing")
        if command.confirmed.referenced_po_number != purchase_order.external_po_number:
            raise CaseConflictError("PO_REFERENCE_MISMATCH", "Receipt references another PO")
        lines_by_number = {line.line_number: line for line in purchase_order.lines}
        try:
            receipt_command = GoodsReceiptCreate(
                purchase_order_id=purchase_order.id,
                external_receipt_number=command.confirmed.external_receipt_number,
                received_at=command.confirmed.received_at,
                lines=[
                    GoodsReceiptLineCreate(
                        purchase_order_line_id=lines_by_number[item.purchase_order_line_number].id,
                        accepted_quantity=item.accepted_quantity,
                    )
                    for item in command.confirmed.lines
                ],
            )
        except KeyError as exc:
            raise CaseConflictError(
                "PO_LINE_NOT_FOUND", "Receipt references an unknown PO line"
            ) from exc
        canonical = GoodsReceipt(
            purchase_order_id=purchase_order.id,
            external_receipt_number=receipt_command.external_receipt_number,
            received_at=receipt_command.received_at,
            request_fingerprint=receipt_request_fingerprint(receipt_command),
            lines=[
                GoodsReceiptLine(
                    purchase_order_line_id=item.purchase_order_line_id,
                    accepted_quantity=item.accepted_quantity,
                )
                for item in receipt_command.lines
            ],
        )
        self.session.add(canonical)
        self.session.flush()
        confirmation = CaseConfirmation(
            case_id=case_id,
            case_document_id=attachment.id,
            extraction_run_id=run.id,
            extractor_version=run.extractor_version,
            canonical_record_type="GOODS_RECEIPT",
            canonical_record_id=canonical.id,
            confirmed_json=payload,
            corrected_fields=corrected,
            correction_reason=command.correction_reason,
            idempotency_key=command.idempotency_key,
            request_fingerprint=fingerprint,
        )
        self.session.add(confirmation)
        payable_case.version += 1
        payable_case.status = self._status_after_confirmation(case_id, attachment.id)
        self._confirmation_event(confirmation, attachment, corrected)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self._confirmation_replay(case_id, command.idempotency_key, fingerprint)
            if concurrent is None:
                raise CaseConflictError(
                    "ATTACHMENT_ALREADY_CONFIRMED",
                    "This attachment already has a confirmation",
                ) from None
            confirmation = concurrent
        self._observe_confirmation(attachment, corrected, payable_case)
        return ConfirmationRead.model_validate(confirmation, from_attributes=True)

    @staticmethod
    def _observe_confirmation(
        attachment: CaseDocument,
        corrected: list[str],
        payable_case: PayableCase,
    ) -> None:
        for field in corrected:
            metrics.add(
                "confirmed_corrections",
                "confirmation",
                role=attachment.role.value,
                field=field,
            )
        if payable_case.status == CaseStatus.READY_TO_MATCH:
            created_at = payable_case.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            metrics.add("case_events", "case", event="READY")
            metrics.observe(
                "case_time_to_ready",
                max(0.0, (datetime.now(UTC) - created_at).total_seconds()),
                "case",
                event="READY",
            )

    def _confirmation_replay(
        self, case_id: uuid.UUID, key: str, fingerprint: str
    ) -> CaseConfirmation | None:
        existing = self.session.scalar(
            select(CaseConfirmation).where(
                CaseConfirmation.case_id == case_id,
                CaseConfirmation.idempotency_key == key,
            )
        )
        if existing is not None and existing.request_fingerprint != fingerprint:
            raise CaseConflictError("IDEMPOTENCY_KEY_REUSED", "Idempotency key payload differs")
        return existing

    def _status_after_confirmation(
        self, case_id: uuid.UUID, current_attachment_id: uuid.UUID
    ) -> CaseStatus:
        active_po = self.session.scalar(
            select(CaseDocument.id).where(
                CaseDocument.case_id == case_id,
                CaseDocument.active_slot == DocumentRole.PURCHASE_ORDER.value,
            )
        )
        if active_po is None:
            return CaseStatus.NEEDS_CONFIRMATION
        confirmed_ids = set(
            self.session.scalars(
                select(CaseConfirmation.case_document_id).where(CaseConfirmation.case_id == case_id)
            )
        )
        confirmed_ids.add(current_attachment_id)
        support_successor = aliased(CaseDocument)
        active_support = set(
            self.session.scalars(
                select(CaseDocument.id).where(
                    CaseDocument.case_id == case_id,
                    (CaseDocument.active_slot == DocumentRole.PURCHASE_ORDER.value)
                    | (
                        CaseDocument.role.in_(
                            (DocumentRole.GOODS_RECEIPT, DocumentRole.DELIVERY_NOTE)
                        )
                        & ~exists().where(support_successor.supersedes_id == CaseDocument.id)
                    ),
                )
            )
        )
        return (
            CaseStatus.READY_TO_MATCH
            if active_support.issubset(confirmed_ids)
            else CaseStatus.NEEDS_CONFIRMATION
        )

    def _confirmation_event(
        self,
        confirmation: CaseConfirmation,
        attachment: CaseDocument,
        corrected: list[str],
    ) -> None:
        self.session.flush()
        append_case_event(
            self.session,
            case_id=attachment.case_id,
            event_key=f"document.confirmed:{confirmation.id}",
            event_type="DOCUMENT_CONFIRMED",
            stage="confirmation",
            status="completed",
            message="Supporting document confirmed into a canonical record",
            document_id=attachment.document_id,
            document_role=attachment.role,
            payload={
                "confirmation_id": str(confirmation.id),
                "canonical_record_type": confirmation.canonical_record_type,
                "corrected_fields": corrected,
            },
        )

    @staticmethod
    def _po_corrected_fields(
        extracted: ExtractedPurchaseOrder,
        confirmed: dict[str, object],
        *,
        amount_provided: list[bool],
    ) -> list[str]:
        pairs = {
            "external_po_number": extracted.po_number.value,
            "issue_date": extracted.issue_date.value,
            "buyer_name": extracted.buyer.value,
            "vendor_name": extracted.vendor.value,
            "currency": extracted.currency.value,
            "subtotal": extracted.subtotal.value,
            "tax": extracted.tax.value,
            "total": extracted.total.value,
        }
        corrected = [
            name
            for name, value in pairs.items()
            if json.loads(json.dumps(value, default=str)) != confirmed.get(name)
        ]
        confirmed_lines = confirmed.get("lines")
        lines_changed = not isinstance(confirmed_lines, list) or len(confirmed_lines) != len(
            extracted.line_items
        )
        if isinstance(confirmed_lines, list):
            for index, (source, candidate) in enumerate(
                zip(extracted.line_items, confirmed_lines, strict=False)
            ):
                if not isinstance(candidate, dict):
                    lines_changed = True
                    continue
                if source.line_number.value != candidate.get("line_number") or (
                    source.description.value != candidate.get("description")
                ):
                    lines_changed = True
                for name in ("ordered_quantity", "unit_price", "line_total"):
                    if name == "line_total" and not amount_provided[index]:
                        continue
                    source_value = getattr(source, name).value
                    candidate_value = candidate.get(name)
                    if source_value is None or candidate_value is None:
                        different = source_value is not None or candidate_value is not None
                    else:
                        different = source_value != Decimal(str(candidate_value))
                    if different:
                        lines_changed = True
                        if name == "line_total":
                            corrected.append(f"lines.{index}.line_total")
        if lines_changed:
            corrected.append("lines")
        return sorted(corrected)

    @staticmethod
    def _receipt_corrected_fields(
        extracted: ExtractedGoodsReceipt, confirmed: dict[str, object]
    ) -> list[str]:
        pairs = {
            "external_receipt_number": extracted.receipt_number.value,
            "referenced_po_number": extracted.referenced_po_number.value,
            "received_at": (
                f"{extracted.received_date.value.isoformat()}T00:00:00Z"
                if extracted.received_date.value is not None
                else None
            ),
            "supplier": extracted.supplier.value,
        }
        corrected = [
            name
            for name, value in pairs.items()
            if json.loads(json.dumps(value, default=str)) != confirmed.get(name)
        ]
        extracted_lines = [
            {
                "description": item.description.value,
                "received_quantity": item.received_quantity.value,
                "accepted_quantity": item.accepted_quantity.value,
                "rejected_quantity": item.rejected_quantity.value,
            }
            for item in extracted.line_items
        ]
        confirmed_lines = confirmed.get("lines")
        normalized_lines = json.loads(json.dumps(extracted_lines, default=str))
        if not isinstance(confirmed_lines, list) or any(
            {
                "description": item.get("description"),
                "received_quantity": item.get("received_quantity"),
                "accepted_quantity": item.get("accepted_quantity"),
                "rejected_quantity": item.get("rejected_quantity"),
            }
            != extracted_line
            for item, extracted_line in zip(confirmed_lines, normalized_lines, strict=False)
            if isinstance(item, dict)
        ) or len(confirmed_lines) != len(normalized_lines):
            corrected.append("lines")
        return sorted(corrected)
