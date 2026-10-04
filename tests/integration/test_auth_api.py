import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import apps.api.security as security
from apps.api.main import app
from invoiceops.auth import OidcVerifier
from invoiceops.config import Settings, get_settings
from invoiceops.models import GoodsReceiptReversal
from tests.integration.test_matching_api import po_payload
from tests.integration.test_review_api import create_review_case
from tests.integration.test_three_way_matching_api import _receipt_payload
from tests.unit.test_auth import AUDIENCE, ISSUER, healthy_handler, signed_token, signing_key


def test_every_application_route_has_an_explicit_policy() -> None:
    actual = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if route.path.startswith("/v1/") and method not in {"HEAD", "OPTIONS"}
    }
    assert actual == set(security.ROUTE_ROLES)


def test_production_refuses_development_authentication() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(environment="production", auth_mode="development")


def test_oidc_protects_routes_roles_sse_and_ignores_spoofed_headers(
    client: TestClient, monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    private, public = signing_key("api-key")
    check = OidcVerifier(
        issuer=ISSUER, audience=AUDIENCE,
        client=httpx.Client(transport=httpx.MockTransport(healthy_handler([public]))),
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        auth_mode="oidc", oidc_issuer=ISSUER, oidc_audience=AUDIENCE,
        database_url="sqlite+pysqlite://",
    )
    monkeypatch.setattr(security, "get_oidc_verifier", lambda _settings: check)

    assert client.get("/v1/me").status_code == 401
    assert client.get("/v1/me", headers={"Authorization": "Bearer broken"}).status_code == 401
    assert client.get("/health/live").status_code == 200
    auditor = signed_token(private, "api-key", roles=["auditor"])
    operator = signed_token(private, "api-key", roles=["operator"])
    reviewer = signed_token(private, "api-key", roles=["reviewer"])

    def headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    assert client.get("/v1/me", headers=headers(auditor)).json()["roles"] == ["auditor"]
    assert client.post("/v1/cases", json={"idempotency_key": "auditor-1"},
                       headers=headers(auditor)).status_code == 403
    assert client.get("/v1/review-cases", headers=headers(operator)).status_code == 403
    assert client.post("/v1/cases", json={"idempotency_key": "operator-1"},
                       headers=headers(operator)).status_code == 201
    assert client.post("/v1/cases", json={"idempotency_key": "reviewer-1"},
                       headers=headers(reviewer)).status_code == 201
    assert client.get("/v1/jobs/00000000-0000-0000-0000-000000000001/events").status_code == 401
    assert client.get(
        "/v1/jobs/00000000-0000-0000-0000-000000000001/events",
        headers=headers(auditor),
    ).status_code == 404
    spoofed = {
        **headers(reviewer), "X-Reviewer-ID": "spoofed", "X-Actor-ID": "spoofed",
        "X-Dev-Roles": "admin",
    }
    assert client.get("/v1/me", headers=spoofed).json()["subject"] == "synthetic-reviewer"
    assert client.get("/v1/review-cases", headers=headers(reviewer)).status_code == 200


def test_review_audit_uses_verified_subject_and_roles(
    client: TestClient, db_session_factory: sessionmaker[Session], monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    review = create_review_case(client, db_session_factory)
    private, public = signing_key("audit-key")
    check = OidcVerifier(
        issuer=ISSUER, audience=AUDIENCE,
        client=httpx.Client(transport=httpx.MockTransport(healthy_handler([public]))),
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        auth_mode="oidc", oidc_issuer=ISSUER, oidc_audience=AUDIENCE,
        database_url="sqlite+pysqlite://",
    )
    monkeypatch.setattr(security, "get_oidc_verifier", lambda _settings: check)
    token = signed_token(private, "audit-key", roles=["reviewer"])
    headers = {"Authorization": f"Bearer {token}", "X-Reviewer-ID": "spoofed"}
    claimed = client.post(
        f"/v1/review-cases/{review['id']}/claim",
        headers=headers, json={"expected_version": review["version"]},
    )
    assert claimed.status_code == 200
    events = client.get(f"/v1/review-cases/{review['id']}/events", headers=headers).json()
    assert events[-1]["actor_id"] == "synthetic-reviewer"
    assert events[-1]["payload"]["actor_roles"] == ["reviewer"]
    audit = client.get(
        f"/v1/review-cases/{review['id']}/audit-verification", headers=headers
    )
    assert audit.status_code == 200


def test_receipt_reversal_audit_uses_verified_identity_and_role(
    client: TestClient, db_session_factory: sessionmaker[Session], monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    po = client.post("/v1/purchase-orders", json=po_payload()).json()
    receipt = client.post("/v1/goods-receipts", json=_receipt_payload(po)).json()
    private, public = signing_key("receipt-key")
    check = OidcVerifier(
        issuer=ISSUER, audience=AUDIENCE,
        client=httpx.Client(transport=httpx.MockTransport(healthy_handler([public]))),
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        auth_mode="oidc", oidc_issuer=ISSUER, oidc_audience=AUDIENCE,
        database_url="sqlite+pysqlite://",
    )
    monkeypatch.setattr(security, "get_oidc_verifier", lambda _settings: check)
    token = signed_token(private, "receipt-key", roles=["reviewer"])
    response = client.post(
        f"/v1/goods-receipts/{receipt['id']}/reverse",
        headers={"Authorization": f"Bearer {token}", "X-Actor-ID": "spoofed"},
        json={"reason": "Synthetic correction"},
    )
    assert response.status_code == 200
    with db_session_factory() as session:
        reversal = session.scalar(select(GoodsReceiptReversal))
        assert reversal is not None
        assert reversal.actor_id == "synthetic-reviewer"
        assert reversal.actor_roles == ["reviewer"]
