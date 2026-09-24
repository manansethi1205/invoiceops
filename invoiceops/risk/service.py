import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from invoiceops.models import (
    ExtractionRun,
    MatchRun,
    PurchaseOrder,
    ReviewCase,
    RiskAssessment,
    RiskFeatureRecord,
    RiskSignal,
)
from invoiceops.risk.engine import SIGNAL_ORDER, assess_duplicate_risk
from invoiceops.risk.normalization import normalize_invoice_number, normalize_vendor
from invoiceops.schemas.extraction import ExtractedField, ExtractionStatus, Invoice
from invoiceops.schemas.risk import (
    DuplicateRiskPolicy,
    RiskAssessmentRead,
    RiskCandidateMetrics,
    RiskFeatureSnapshot,
    RiskSignalRead,
)

CURRENT_DUPLICATE_RISK_POLICY_VERSION = "duplicate-risk-v1"


def current_duplicate_risk_policy() -> DuplicateRiskPolicy:
    return DuplicateRiskPolicy(version=CURRENT_DUPLICATE_RISK_POLICY_VERSION)


def select_effective_assessment(run: MatchRun) -> RiskAssessment | None:
    return next(
        (
            assessment
            for assessment in run.risk_assessments
            if assessment.policy_version == run.risk_policy_version
        ),
        None,
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
        candidate_metrics=RiskCandidateMetrics.model_validate(assessment.candidate_metrics),
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
    def __init__(self, session: Session, policy: DuplicateRiskPolicy | None = None) -> None:
        self.session = session
        self.policy = policy or current_duplicate_risk_policy()

    def ensure(
        self,
        run: MatchRun,
        purchase_order: PurchaseOrder,
        invoice: Invoice,
    ) -> RiskServiceResult:
        existing = self._find_for_match(run.id)
        if existing is not None:
            features = build_feature_snapshot(run, purchase_order, invoice)
            self._ensure_feature_record(features)
            return RiskServiceResult(existing, False)

        features = build_feature_snapshot(run, purchase_order, invoice)
        feature_record = self._ensure_feature_record(features)
        historical_count, candidate_records = self._candidate_records(feature_record)
        historical = [self._record_to_snapshot(item) for item in candidate_records]
        result = assess_duplicate_risk(features, historical, self.policy)
        comparison_count = sum(
            item.complete
            and item.match_run_id != features.match_run_id
            and item.document_id != features.document_id
            for item in historical
        )
        reduction = (
            Decimal("1") - (Decimal(len(candidate_records)) / Decimal(historical_count))
            if historical_count
            else Decimal("0")
        )
        metrics = RiskCandidateMetrics(
            historical_record_count=historical_count,
            candidate_record_count=len(candidate_records),
            candidate_reduction_rate=reduction,
            comparison_count=comparison_count,
        )
        assessment = RiskAssessment(
            match_run_id=run.id,
            policy_version=self.policy.version,
            policy_snapshot=self.policy.model_dump(mode="json"),
            disposition=result.disposition,
            feature_snapshot=result.features.model_dump(mode="json"),
            candidate_metrics=metrics.model_dump(mode="json"),
        )
        run.risk_policy_version = self.policy.version
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
        run = self.session.get(MatchRun, match_run_id)
        if run is None:
            raise RiskAssessmentNotFoundError
        assessment = self._find_for_match(match_run_id, run.risk_policy_version)
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

    def _find_for_match(
        self, match_run_id: uuid.UUID, policy_version: str | None = None
    ) -> RiskAssessment | None:
        return self.session.scalar(
            select(RiskAssessment)
            .where(
                RiskAssessment.match_run_id == match_run_id,
                RiskAssessment.policy_version == (policy_version or self.policy.version),
            )
            .options(selectinload(RiskAssessment.signals))
        )

    def _ensure_feature_record(self, features: RiskFeatureSnapshot) -> RiskFeatureRecord:
        existing = self.session.scalar(
            select(RiskFeatureRecord).where(RiskFeatureRecord.match_run_id == features.match_run_id)
        )
        if existing is not None:
            return existing
        record = RiskFeatureRecord(
            match_run_id=features.match_run_id,
            normalized_vendor=features.normalized_vendor,
            normalized_invoice_number=features.normalized_invoice_number,
            invoice_date=features.invoice_date,
            currency=features.currency,
            total=Decimal(features.total) if features.total is not None else None,
            purchase_order_id=features.purchase_order_id,
            document_id=features.document_id,
            extraction_run_id=features.extraction_run_id,
            missing_fields=list(features.missing_fields),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def _candidate_records(self, current: RiskFeatureRecord) -> tuple[int, list[RiskFeatureRecord]]:
        base_conditions = (
            RiskFeatureRecord.match_run_id != current.match_run_id,
            RiskFeatureRecord.document_id != current.document_id,
        )
        historical_count = int(
            self.session.scalar(
                select(func.count()).select_from(RiskFeatureRecord).where(*base_conditions)
            )
            or 0
        )
        plausible = [RiskFeatureRecord.purchase_order_id == current.purchase_order_id]
        if current.normalized_vendor and current.normalized_invoice_number:
            plausible.append(
                (RiskFeatureRecord.normalized_vendor == current.normalized_vendor)
                & (RiskFeatureRecord.normalized_invoice_number == current.normalized_invoice_number)
            )
        if current.normalized_vendor and current.currency and current.invoice_date:
            earliest = current.invoice_date - timedelta(days=self.policy.date_window_days)
            latest = current.invoice_date + timedelta(days=self.policy.date_window_days)
            plausible.append(
                (RiskFeatureRecord.normalized_vendor == current.normalized_vendor)
                & (RiskFeatureRecord.currency == current.currency)
                & RiskFeatureRecord.invoice_date.between(earliest, latest)
            )
        candidates = list(
            self.session.scalars(
                select(RiskFeatureRecord)
                .where(*base_conditions, or_(*plausible))
                .order_by(RiskFeatureRecord.created_at, RiskFeatureRecord.id)
            )
        )
        return historical_count, candidates

    @staticmethod
    def _record_to_snapshot(record: RiskFeatureRecord) -> RiskFeatureSnapshot:
        return RiskFeatureSnapshot(
            normalized_vendor=record.normalized_vendor,
            normalized_invoice_number=record.normalized_invoice_number,
            invoice_date=record.invoice_date,
            currency=record.currency,
            total=format(record.total, "f") if record.total is not None else None,
            purchase_order_id=record.purchase_order_id,
            document_id=record.document_id,
            extraction_run_id=record.extraction_run_id,
            match_run_id=record.match_run_id,
            missing_fields=tuple(record.missing_fields),
        )
