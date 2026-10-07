# Authentication and authorization

InvoiceOps never authorizes or executes payment. Matching, human resolution and payment authorization remain distinct.
Supporting extraction selection is version-aware but never creates canonical PO or receipt data;
explicit reviewer confirmation remains necessary in both authentication modes.

## Policy

| Action | Operator | Reviewer | Auditor | Admin |
| --- | :---: | :---: | :---: | :---: |
| Read payable cases, documents, extraction and matching | Yes | Yes | Yes | Yes |
| Create cases, upload, create POs/receipts, run matching | Yes | Yes | No | Yes |
| Read review queue and tamper-evident history | No | Yes | Yes | Yes |
| Confirm supporting records, claim/comment/release/resolve, reverse receipts | No | Yes | No | Yes |

Every `/v1` route is in the explicit allowlist in `apps/api/security.py`. New routes default to `403` until assigned a policy. The API verifies bearer access tokens in OIDC mode: RS256 only, exact issuer and audience, signature from discovered JWKS, `exp`, `nbf`, `sub`, and a nonempty `roles` array. JWKS refreshes once on an unknown key ID and periodically on its bounded TTL. No verification failure falls back to development identity headers. `/health/live`, `/healthz` and coarse `/health/ready` are public; OpenAPI and Swagger are disabled in OIDC mode. There is no public `/metrics` route.

## Local mode

`AUTH_MODE=development` on the API and `WEB_AUTH_MODE=development` on the web app are for local testing only. The login page offers synthetic operator, reviewer, auditor and admin identities. The synthetic cookie is short-lived and signed with a deliberately public development key; **it is not production authentication**. The API's `X-Actor-ID`, `X-Reviewer-ID`, and `X-Dev-Roles` compatibility headers are accepted only in this mode. `ENVIRONMENT=production` rejects development API auth at startup; `WEB_ENVIRONMENT=production` rejects development web auth during configuration and at request time.

## OIDC mode

Configure the API with `ENVIRONMENT=production`, `AUTH_MODE=oidc`, `OIDC_ISSUER` and `OIDC_AUDIENCE`. Configure web with `WEB_ENVIRONMENT=production`, `WEB_AUTH_MODE=oidc`, `WEB_PUBLIC_ORIGIN`, `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI`, `AUTH_SESSION_REDIS_URL`, and `INVOICEOPS_API_URL`. Secrets must come from a secret manager, not `.env` in a public deployment. Use TLS end-to-end and register the exact callback URI. The identity provider must issue signed JWT **access tokens** for the API audience with the configured role claim; opaque tokens are not supported. Configure refresh-token rotation and role-claim consistency at the provider.

The browser uses authorization-code flow with PKCE, state and nonce. An opaque, HTTP-only, SameSite=Lax cookie references a Redis session containing the access/refresh tokens. The Next.js backend-for-frontend renews expiring tokens and streams API responses and SSE directly without buffering. Browser-provided Authorization and development actor headers are stripped. Route layouts verify the session server-side, while the API is the authorization authority. Visible controls are role-aware, but hidden controls do not grant or deny access.

OIDC requires reachable discovery/JWKS endpoints and Redis. If either is unavailable, verification/session access fails closed; users see a provider or session error and may retry later. Review audit events record the verified subject and role context, not tokens. Existing non-review event schemas retain their historical actor metadata; do not infer a role from legacy events.

Default CI uses ephemeral RSA keys and synthetic JWTs, while its normal browser
suite uses development identities. An **opt-in** local Keycloak realm and
browser/API walkthrough are described in [the OIDC smoke runbook](oidc-smoke.md).
The fixture uses deliberately public synthetic credentials and is never part of
the normal Compose startup. The local Keycloak browser suite passed 4/4 on
2026-10-08 with the pinned synthetic realm; this is a local integration result,
not a claim about CI or a production provider.
Before production deployment, validate the chosen real provider, external
secret management, TLS, multi-instance refresh coordination, Redis TLS/HA,
incident procedures, and a deployment-specific threat review.
