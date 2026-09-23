import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from invoiceops.models import (
    ExtractionRun,
    MatchRun,
    PurchaseOrder,
    ReviewCase,
    RiskAssessment,
    RiskSignal,
)
from invoiceops.risk.engine import SIGNAL_ORDER, assess_duplicate_risk
from invoiceops.risk.normalization import normalize_invoice_number, normalize_vendor
from invoiceops.schemas.extraction import ExtractedField, ExtractionStatus, Invoice
from invoiceops.schemas.risk import (
    DuplicateRiskPolicy,
    RiskAssessmentRead,
    RiskFeatureSnapshot,
    RiskSignalRead,
)


class RiskAssessmentNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class RiskServiceResult:
    assessment: RiskAssessment
    created: bool


@dataclass(frozen=True)
class RiskReconciliationResult:
    inspected: int
    created: int
    reused: int
    failed: int


def build_feature_snapshot(
    run: MatchRun, purchase_order: PurchaseOrder, invoice: Invoice
) -> RiskFeatureSnapshot:
    missing: list[str] = []
    normalized_vendor = (
        normalize_vendor(purchase_order.vendor_name) if purchase_order.vendor_name else None
    )
    if not normalized_vendor:
        normalized_vendor = None
        missing.append("normalized_vendor")

    invoice_number = _extracted_value(invoice.invoice_number)
    normalized_invoice_number = (
        normalize_invoice_number(invoice_number) if invoice_number is not None else None
    )
    if not normalized_invoice_number:
        normalized_invoice_number = None
        missing.append("normalized_invoice_number")

    invoice_date = _extracted_value(invoice.invoice_date)
    if invoice_date is None:
        missing.append("invoice_date")
    currency = _extracted_value(invoice.currency)
    if currency is None:
        missing.append("currency")
    total = _extracted_value(invoice.total)
    if total is None:
        missing.append("total")

    return RiskFeatureSnapshot(
        normalized_vendor=normalized_vendor,
        normalized_invoice_number=normalized_invoice_number,
        invoice_date=invoice_date,
        currency=currency.upper() if currency is not None else None,
        total=format(total, "f") if total is not None else None,
        purchase_order_id=run.purchase_order_id,
        document_id=run.document_id,
        extraction_run_id=run.extraction_run_id,
        match_run_id=run.id,
        missing_fields=tuple(missing),
    )


def _extracted_value[T](field: ExtractedField[T]) -> T | None:
    return (
        field.value
        if field.status == ExtractionStatus.EXTRACTED and field.value is not None
        else None
    )


def risk_assessment_to_read(
    assessment: RiskAssessment, review_case: ReviewCase | None
) -> RiskAssessmentRead:
    features = RiskFeatureSnapshot.model_validate(assessment.feature_snapshot)
    signals = [
        RiskSignalRead(
            id=signal.id,
            code=signal.code,
            severity=signal.severity,
            comparison_match_run_id=signal.comparison_match_run_id,
            observed=signal.observed,
            reference=signal.reference,
            explanation=signal.explanation,
            created_at=signal.created_at,
        )
        for signal in sorted(
            assessment.signals,
            key=lambda item: (
                SIGNAL_ORDER[item.code],
                str(item.comparison_match_run_id or ""),
            ),
        )
    ]
    return RiskAssessmentRead(
        id=assessment.id,
        match_run_id=assessment.match_run_id,
        policy_version=assessment.policy_version,
        policy_snapshot=DuplicateRiskPolicy.model_validate(assessment.policy_snapshot),
        disposition=assessment.disposition,
        feature_snapshot=features,
        feature_complete=features.complete,
        signals=signals,
        compared_match_run_ids=sorted(
            {
                signal.comparison_match_run_id
                for signal in assessment.signals
                if signal.comparison_match_run_id is not None
            },
            key=str,
        ),
        match_decision=assessment.match_run.decision.value,
        review_case_id=review_case.id if review_case is not None else None,
        review_status=review_case.status.value if review_case is not None else None,
        human_resolution=(
            review_case.resolution.value
            if review_case is not None and review_case.resolution is not None
            else None
        ),
        payment_authorized=False,
        created_at=assessment.created_at,
    )


class DuplicateRiskService:
    def __init__(
        self, session: Session, policy: DuplicateRiskPolicy | None = None
    ) -> None:
        self.session = session
        self.policy = policy or DuplicateRiskPolicy()

    def ensure(
        self,
        run: MatchRun,
        purchase_order: PurchaseOrder,
        invoice: Invoice,
    ) -> RiskServiceResult:
        existing = self._find_for_match(run.id)
        if existing is not None:
            return RiskServiceResult(existing, False)

        features = build_feature_snapshot(run, purchase_order, invoice)
        historical = [
            RiskFeatureSnapshot.model_validate(item.feature_snapshot)
            for item in self.session.scalars(
                select(RiskAssessment)
                .where(
                    RiskAssessment.policy_version == self.policy.version,
                    RiskAssessment.match_run_id != run.id,
                )
                .order_by(RiskAssessment.created_at, RiskAssessment.id)
            )
        ]
        result = assess_duplicate_risk(features, historical, self.policy)
        assessment = RiskAssessment(
            match_run_id=run.id,
            policy_version=self.policy.version,
            policy_snapshot=self.policy.model_dump(mode="json"),
            disposition=result.disposition,
            feature_snapshot=result.features.model_dump(mode="json"),
        )
        self.session.add(assessment)
        self.session.flush()
        for signal in result.signals:
            if signal.comparison_match_run_id == run.id:
                raise ValueError("risk comparison cannot reference its own match run")
            self.session.add(
                RiskSignal(
                    risk_assessment_id=assessment.id,
                    code=signal.code,
                    severity=signal.severity,
                    comparison_match_run_id=signal.comparison_match_run_id,
                    observed=signal.observed,
                    reference=signal.reference,
                    explanation=signal.explanation,
                )
            )
        self.session.flush()
        return RiskServiceResult(self.get(assessment.id), True)

    def get(self, assessment_id: uuid.UUID) -> RiskAssessment:
        assessment = self.session.scalar(
            select(RiskAssessment)
            .where(RiskAssessment.id == assessment_id)
            .options(selectinload(RiskAssessment.signals))
        )
        if assessment is None:
            raise RiskAssessmentNotFoundError
        return assessment

    def get_for_match(self, match_run_id: uuid.UUID) -> RiskAssessment:
        assessment = self._find_for_match(match_run_id)
        if assessment is None:
            raise RiskAssessmentNotFoundError
        return assessment

    def read(self, assessment: RiskAssessment) -> RiskAssessmentRead:
        review_case = self.session.scalar(
            select(ReviewCase).where(ReviewCase.match_run_id == assessment.match_run_id)
        )
        return risk_assessment_to_read(assessment, review_case)

    def reconcile(self) -> RiskReconciliationResult:
        runs = list(
            self.session.scalars(select(MatchRun).order_by(MatchRun.created_at, MatchRun.id))
        )
        created = reused = failed = 0
        from invoiceops.review.service import ensure_review_case

        for run in runs:
            try:
                with self.session.begin_nested():
                    extraction = self.session.get(ExtractionRun, run.extraction_run_id)
                    purchase_order = self.session.get(PurchaseOrder, run.purchase_order_id)
                    if (
                        extraction is None
                        or extraction.output_json is None
                        or purchase_order is None
                    ):
                        raise ValueError("historical match lacks immutable source data")
                    invoice = Invoice.model_validate(extraction.output_json)
                    result = self.ensure(run, purchase_order, invoice)
                    created += int(result.created)
                    reused += int(not result.created)
                    ensure_review_case(self.session, run, result.assessment)
            except (ValueError, TypeError):
                failed += 1
        self.session.commit()
        return RiskReconciliationResult(len(runs), created, reused, failed)

    def _find_for_match(self, match_run_id: uuid.UUID) -> RiskAssessment | None:
        return self.session.scalar(
            select(RiskAssessment)
            .where(
                RiskAssessment.match_run_id == match_run_id,
                RiskAssessment.policy_version == self.policy.version,
            )
            .options(selectinload(RiskAssessment.signals))
        )
