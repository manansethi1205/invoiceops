"""Default-deny API authorization; UI visibility never grants access."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from invoiceops.auth import (
    IdentityProviderUnavailable,
    OidcVerifier,
    Principal,
    Role,
    TokenRejected,
)
from invoiceops.config import Settings, get_settings

READ = frozenset(Role)
OPERATION = frozenset({Role.OPERATOR, Role.REVIEWER, Role.ADMIN})
REVIEW = frozenset({Role.REVIEWER, Role.ADMIN})
REVIEW_READ = frozenset({Role.REVIEWER, Role.AUDITOR, Role.ADMIN})

# Explicit route templates prevent a newly added endpoint from inheriting broad access.
ROUTE_ROLES: dict[tuple[str, str], frozenset[Role]] = {
    ("GET", "/v1/me"): READ,
    ("POST", "/v1/cases"): OPERATION,
    ("GET", "/v1/cases/{case_id}"): READ,
    ("POST", "/v1/cases/{case_id}/documents"): OPERATION,
    ("GET", "/v1/cases/{case_id}/documents"): READ,
    ("GET", "/v1/cases/{case_id}/extractions"): READ,
    ("GET", "/v1/cases/{case_id}/events"): READ,
    ("POST", "/v1/cases/{case_id}/purchase-order/confirm"): REVIEW,
    ("POST", "/v1/cases/{case_id}/receipts/{document_id}/confirm"): REVIEW,
    ("POST", "/v1/cases/{case_id}/match"): OPERATION,
    ("POST", "/v1/invoices"): OPERATION,
    ("GET", "/v1/invoices"): READ,
    ("GET", "/v1/invoices/{document_id}"): READ,
    ("GET", "/v1/documents/{document_id}/content"): READ,
    ("GET", "/v1/dashboard/summary"): READ,
    ("GET", "/v1/jobs/{job_id}"): READ,
    ("GET", "/v1/jobs/{job_id}/events"): READ,
    ("GET", "/v1/invoices/{document_id}/extraction"): READ,
    ("POST", "/v1/purchase-orders"): OPERATION,
    ("GET", "/v1/purchase-orders"): READ,
    ("GET", "/v1/purchase-orders/{purchase_order_id}"): READ,
    ("POST", "/v1/goods-receipts"): OPERATION,
    ("GET", "/v1/goods-receipts"): READ,
    ("GET", "/v1/purchase-orders/{purchase_order_id}/goods-receipts"): READ,
    ("GET", "/v1/goods-receipts/{receipt_id}"): READ,
    ("POST", "/v1/goods-receipts/{receipt_id}/reverse"): REVIEW,
    ("POST", "/v1/documents/{document_id}/matches"): OPERATION,
    ("GET", "/v1/matches/{match_run_id}"): READ,
    ("GET", "/v1/matches/{match_run_id}/three-way-context"): READ,
    ("GET", "/v1/matches/{match_run_id}/risk"): READ,
    ("GET", "/v1/risk-assessments/{risk_assessment_id}"): READ,
    ("GET", "/v1/review-cases"): REVIEW_READ,
    ("GET", "/v1/review-cases/{case_id}"): REVIEW_READ,
    ("POST", "/v1/review-cases/{case_id}/claim"): REVIEW,
    ("POST", "/v1/review-cases/{case_id}/release"): REVIEW,
    ("POST", "/v1/review-cases/{case_id}/comments"): REVIEW,
    ("POST", "/v1/review-cases/{case_id}/resolve"): REVIEW,
    ("GET", "/v1/review-cases/{case_id}/events"): REVIEW_READ,
    ("GET", "/v1/review-cases/{case_id}/audit-verification"): REVIEW_READ,
}


@lru_cache(maxsize=8)
def _verifier(issuer: str, audience: str, roles_claim: str, ttl_seconds: int) -> OidcVerifier:
    return OidcVerifier(
        issuer=issuer, audience=audience, roles_claim=roles_claim, ttl_seconds=ttl_seconds
    )


def get_oidc_verifier(settings: Settings) -> OidcVerifier:
    return _verifier(
        settings.oidc_issuer,
        settings.oidc_audience,
        settings.oidc_roles_claim,
        settings.oidc_jwks_ttl_seconds,
    )


def resolve_principal(request: Request, settings: Settings) -> Principal:
    if settings.auth_mode == "development":
        template = getattr(request.scope.get("route"), "path", "")
        if template.startswith("/v1/review-cases/") and request.method == "POST":
            if not request.headers.get("X-Reviewer-ID", "").strip():
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "INVALID_REVIEWER_ID",
                        "message": "X-Reviewer-ID must contain 1 to 100 nonblank characters",
                    },
                )
        if template == "/v1/goods-receipts/{receipt_id}/reverse":
            if not request.headers.get("X-Actor-ID", "").strip():
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "INVALID_ACTOR_ID",
                        "message": "X-Actor-ID must contain 1 to 100 nonblank characters",
                    },
                )
        subject = (
            request.headers.get("X-Reviewer-ID")
            or request.headers.get("X-Actor-ID")
            or "local-developer"
        ).strip()
        if not subject or len(subject) > 100:
            raise HTTPException(status_code=422, detail="Invalid development actor")
        raw_roles = request.headers.get("X-Dev-Roles", "admin").split(",")
        try:
            roles = frozenset(Role(value.strip()) for value in raw_roles)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid development role") from exc
        return Principal(subject=subject, roles=roles)
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer ") or not authorization[7:].strip():
        raise HTTPException(
            status_code=401,
            detail="Bearer access token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return get_oidc_verifier(settings).verify(authorization[7:].strip())
    except TokenRejected as exc:
        raise HTTPException(
            status_code=401, detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except IdentityProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail="Identity verification unavailable") from exc


def authorize_request(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    route = request.scope.get("route")
    template = getattr(route, "path", "")
    if template in {"/health/live", "/healthz", "/health/ready"}:
        return
    required = ROUTE_ROLES.get((request.method, template))
    if required is None:
        raise HTTPException(status_code=403, detail="Route has no authorization policy")
    principal = resolve_principal(request, settings)
    if not principal.roles.intersection(required):
        raise HTTPException(status_code=403, detail="Insufficient role")
    request.state.principal = principal


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal
