"""Vendor-neutral, fail-closed OIDC access-token verification."""

import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

import httpx
import jwt


class Role(StrEnum):
    OPERATOR = "operator"
    REVIEWER = "reviewer"
    AUDITOR = "auditor"
    ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: frozenset[Role]


class TokenRejected(Exception):
    """Token is absent, malformed, expired, or unverifiable."""


class IdentityProviderUnavailable(Exception):
    """Discovery or key refresh could not be completed."""


class OidcVerifier:
    ALGORITHMS = ("RS256",)

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        roles_claim: str = "roles",
        ttl_seconds: int = 300,
        client: httpx.Client | None = None,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.roles_claim = roles_claim
        self.ttl_seconds = ttl_seconds
        self.client = client or httpx.Client(timeout=5.0, follow_redirects=False)
        self._lock = threading.RLock()
        self._keys: dict[str, Any] = {}
        self._expires_at = 0.0
        self._jwks_uri: str | None = None

    def verify(self, token: str) -> Principal:
        if len(token) > 16_384:
            raise TokenRejected("token too large")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise TokenRejected("malformed token") from exc
        if header.get("alg") not in self.ALGORITHMS:
            raise TokenRejected("disallowed algorithm")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid or len(kid) > 256:
            raise TokenRejected("missing signing key identifier")
        key = self._key_for(kid)
        if key is None:
            raise TokenRejected("unknown signing key")
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=list(self.ALGORITHMS),
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "nbf", "iss", "aud", "sub"]},
                leeway=0,
            )
        except jwt.PyJWTError as exc:
            raise TokenRejected("invalid token claims or signature") from exc
        subject = claims.get("sub")
        raw_roles = claims.get(self.roles_claim)
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 100:
            raise TokenRejected("invalid subject")
        if not isinstance(raw_roles, list) or not raw_roles:
            raise TokenRejected("missing roles")
        try:
            roles = frozenset(Role(value) for value in raw_roles if isinstance(value, str))
        except ValueError as exc:
            raise TokenRejected("unknown role") from exc
        if len(roles) != len(raw_roles) or not roles:
            raise TokenRejected("invalid roles")
        return Principal(subject=subject, roles=roles)

    def _key_for(self, kid: str) -> Any | None:
        with self._lock:
            now = time.monotonic()
            if now >= self._expires_at:
                self._refresh()
            key = self._keys.get(kid)
            if key is None:
                # One controlled refresh permits rotation; never loop on an unknown kid.
                self._refresh()
                key = self._keys.get(kid)
            return key

    def _refresh(self) -> None:
        try:
            if self._jwks_uri is None:
                discovery_url = f"{self.issuer.rstrip('/')}/.well-known/openid-configuration"
                response = self.client.get(discovery_url)
                response.raise_for_status()
                metadata = response.json()
                if not isinstance(metadata, dict) or metadata.get("issuer") != self.issuer:
                    raise ValueError("issuer mismatch")
                jwks_uri = metadata.get("jwks_uri")
                if not isinstance(jwks_uri, str) or not self._trusted_uri(jwks_uri):
                    raise ValueError("invalid JWKS URI")
                self._jwks_uri = jwks_uri
            response = self.client.get(self._jwks_uri)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
                raise ValueError("invalid JWKS")
            keys: dict[str, Any] = {}
            if len(data["keys"]) > 50:
                raise ValueError("JWKS exceeds key limit")
            for item in data["keys"]:
                if not isinstance(item, dict):
                    continue
                kid = item.get("kid")
                if (
                    isinstance(kid, str)
                    and item.get("kty") == "RSA"
                    and item.get("use", "sig") == "sig"
                    and item.get("alg", "RS256") == "RS256"
                ):
                    keys[kid] = jwt.PyJWK.from_dict(item, algorithm="RS256").key
            if not keys:
                raise ValueError("JWKS has no allowed signing keys")
            self._keys = keys
            self._expires_at = time.monotonic() + self.ttl_seconds
        except (httpx.HTTPError, ValueError, jwt.PyJWTError) as exc:
            raise IdentityProviderUnavailable("identity provider unavailable") from exc

    def _trusted_uri(self, value: str) -> bool:
        parsed = urlparse(value)
        issuer = urlparse(self.issuer)
        return (
            (parsed.scheme == "https" or (issuer.scheme == "http" and parsed.scheme == "http"))
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
        )
