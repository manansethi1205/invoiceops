import base64
import time
from collections.abc import Callable

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from invoiceops.auth import IdentityProviderUnavailable, OidcVerifier, Role, TokenRejected

ISSUER = "https://issuer.example.test"
AUDIENCE = "invoiceops-api"


def signing_key(kid: str) -> tuple[rsa.RSAPrivateKey, dict[str, str]]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_numbers()

    def encoded(value: int) -> str:
        body = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(body).rstrip(b"=").decode()

    return private, {
        "kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid,
        "n": encoded(public.n), "e": encoded(public.e),
    }


def signed_token(
    private: rsa.RSAPrivateKey, kid: str, **changes: object
) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": ISSUER, "aud": AUDIENCE, "sub": "synthetic-reviewer",
        "roles": ["reviewer"], "exp": now + 300, "nbf": now - 1,
    }
    claims.update(changes)
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": kid})


def verifier(handler: Callable[[httpx.Request], httpx.Response]) -> OidcVerifier:
    return OidcVerifier(
        issuer=ISSUER, audience=AUDIENCE,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def healthy_handler(jwks: list[dict[str, str]]) -> Callable[[httpx.Request], httpx.Response]:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/jwks"})
        return httpx.Response(200, json={"keys": jwks})

    return handle


def test_signed_token_and_required_claims() -> None:
    private, public = signing_key("one")
    check = verifier(healthy_handler([public]))
    assert check.verify(signed_token(private, "one")).roles == frozenset({Role.REVIEWER})
    invalid: list[dict[str, object]] = [
        {"exp": int(time.time()) - 1},
        {"nbf": int(time.time()) + 300},
        {"iss": "https://other.example.test"},
        {"aud": "wrong-audience"},
        {"sub": ""},
        {"roles": []},
    ]
    for changes in invalid:
        with pytest.raises(TokenRejected):
            check.verify(signed_token(private, "one", **changes))
    with pytest.raises(TokenRejected):
        check.verify("malformed")
    with pytest.raises(TokenRejected):
        check.verify(
            jwt.encode(
                {"sub": "fake"},
                "synthetic-secret-32-bytes-long-for-test",
                algorithm="HS256",
                headers={"kid": "one"},
            )
        )


def test_unknown_kid_refreshes_once_and_outage_fails_closed() -> None:
    first_private, first_public = signing_key("first")
    second_private, second_public = signing_key("second")
    keys = [first_public]
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": f"{ISSUER}/jwks"})
        calls += 1
        return httpx.Response(200, json={"keys": keys})

    check = verifier(handle)
    assert check.verify(signed_token(first_private, "first")).subject == "synthetic-reviewer"
    keys.append(second_public)
    assert check.verify(signed_token(second_private, "second")).subject == "synthetic-reviewer"
    assert calls == 2
    with pytest.raises(TokenRejected):
        check.verify(signed_token(second_private, "unknown"))
    assert calls == 3

    def outage(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic outage")

    with pytest.raises(IdentityProviderUnavailable):
        verifier(outage).verify(signed_token(first_private, "first"))


def test_discovery_issuer_must_match_exactly() -> None:
    private, public = signing_key("one")

    def wrong_issuer(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={"issuer": f"{ISSUER}/", "jwks_uri": f"{ISSUER}/jwks"})
        return httpx.Response(200, json={"keys": [public]})

    with pytest.raises(IdentityProviderUnavailable):
        verifier(wrong_issuer).verify(signed_token(private, "one"))


def test_discovered_jwks_can_use_a_separate_https_host_but_not_http() -> None:
    private, public = signing_key("one")

    def remote_keys(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={
                "issuer": ISSUER, "jwks_uri": "https://keys.example.test/jwks",
            })
        assert request.url.host == "keys.example.test"
        return httpx.Response(200, json={"keys": [public]})

    principal = verifier(remote_keys).verify(signed_token(private, "one"))
    assert principal.subject == "synthetic-reviewer"

    def insecure_keys(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={
                "issuer": ISSUER, "jwks_uri": "http://keys.example.test/jwks",
            })
        return httpx.Response(200, json={"keys": [public]})

    with pytest.raises(IdentityProviderUnavailable):
        verifier(insecure_keys).verify(signed_token(private, "one"))
