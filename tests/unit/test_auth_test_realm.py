"""Static safety checks for the opt-in synthetic Keycloak fixture."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_local_realm_has_explicit_api_claims_and_only_synthetic_users() -> None:
    realm = json.loads(
        (ROOT / "infrastructure/auth-test/invoiceops-realm.json").read_text(
            encoding="utf-8"
        )
    )
    assert realm["realm"] == "invoiceops"
    assert realm["sslRequired"] == "none"  # Strictly local start-dev only.
    assert {user["username"] for user in realm["users"]} == {
        "operator", "reviewer", "auditor", "admin"
    }
    assert all(
        user["attributes"]["invoiceops_roles"] == [user["username"]]
        for user in realm["users"]
    )
    assert all(user["email"].endswith("@example.invalid") for user in realm["users"])
    clients = {client["clientId"]: client for client in realm["clients"]}
    assert clients["invoiceops-api"]["bearerOnly"]
    web = clients["invoiceops-web"]
    assert web["publicClient"] is False
    assert web["directAccessGrantsEnabled"] is False
    assert web["redirectUris"] == ["http://127.0.0.1:3000/api/auth/callback"]
    mappers = {mapper["name"]: mapper for mapper in web["protocolMappers"]}
    roles = mappers["invoiceops-top-level-roles"]
    assert roles["config"]["claim.name"] == "roles"
    assert roles["config"]["multivalued"] == "true"
    assert roles["config"]["access.token.claim"] == "true"
    audience = mappers["invoiceops-api-audience"]
    assert audience["protocolMapper"] == "oidc-audience-mapper"
    assert audience["config"]["included.client.audience"] == "invoiceops-api"
    local_nbf = mappers["invoiceops-local-not-before"]
    assert local_nbf["config"]["claim.name"] == "nbf"
    assert local_nbf["config"]["jsonType.label"] == "long"


def test_keycloak_service_is_opt_in_and_bound_to_loopback() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    service = compose.split("  keycloak:\n", 1)[1].split("\n  web:\n", 1)[0]
    assert 'profiles: ["auth-test"]' in service
    assert '"127.0.0.1:8080:8080"' in service
    assert "start-dev" in service
    assert "--import-realm" in service
