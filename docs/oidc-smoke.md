# Local OIDC smoke test (synthetic identities only)

Measured local result on 2026-10-08: **4/4 opt-in browser tests passed** with
the pinned synthetic realm, host-run API/worker/web and Docker data services.
Repeat the commands below on another machine before treating the setup as
portable; this suite is not part of default CI.

This opt-in walkthrough uses the pinned Keycloak `auth-test` Compose service in
`start-dev` mode. Its realm, four users, passwords and web-client secret are
**public test fixtures**, not deployable credentials. Keycloak uses ephemeral
development storage. Do not use this configuration or HTTP transport outside
localhost, and do not upload real financial documents.

All three participants use the exact issuer
`http://localhost:8080/realms/invoiceops`: the browser, the host-run Next.js
server, and the host-run FastAPI server. Only Keycloak and data services run in
Compose; this avoids Docker DNS names appearing in the signed `iss` claim.
Production still requires an HTTPS issuer and real secret management.

From the repository root in PowerShell, start the opt-in services:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose --profile auth-test up -d postgres redis object-storage keycloak
docker compose --profile auth-test ps
curl.exe --noproxy "*" --fail http://localhost:8080/realms/invoiceops/.well-known/openid-configuration
```

Wait until discovery responds before continuing. If port 8080, 5432, 6379 or
9000 is occupied, stop the conflicting local service; do not change the issuer
hostname in only one component. The imported realm contains a confidential
`invoiceops-web` client, an `invoiceops-api` audience, top-level `roles` claim,
and synthetic operator/reviewer/auditor/admin accounts. The fixture user
password is `LocalOnly-User-ChangeMe123!`; it is not a secret. A fixed local
`nbf` claim is mapped into access tokens because the API intentionally requires
one and Keycloak may omit this optional claim by default. Real provider policy
must define its own meaningful not-before behavior.

After changing the synthetic realm JSON, recreate **only** its disposable
container to re-import it:

```powershell
docker compose --profile auth-test up -d --force-recreate --no-deps keycloak
```

In an API PowerShell window at the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
. .\scripts\auth-test-env.ps1
uv sync
uv run alembic upgrade head
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

In a second PowerShell window at the root, run the extraction worker:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
. .\scripts\auth-test-env.ps1
uv run celery -A workers.extraction.celery_app:celery_app worker --loglevel=INFO --pool=solo
```

In a third PowerShell window at the root, build and run the web app:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
. .\scripts\auth-test-env.ps1
$nodeDir = (Resolve-Path '.tools\node-v24.17.0-win-x64').Path
$env:Path = "$nodeDir;$env:Path"
corepack.cmd pnpm@11.24.0 --dir web install --frozen-lockfile
corepack.cmd pnpm@11.24.0 --dir web build
$env:HOSTNAME = '127.0.0.1'
$env:PORT = '3000'
node web/scripts/start-standalone.mjs
```

In a fourth window, generate disposable inputs and run the opt-in browser test:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
. .\scripts\auth-test-env.ps1
uv run python scripts/generate_oidc_smoke_documents.py
$nodeDir = (Resolve-Path '.tools\node-v24.17.0-win-x64').Path
$env:Path = "$nodeDir;$env:Path"
Set-Location web
corepack.cmd pnpm@11.24.0 exec playwright install chromium
corepack.cmd pnpm@11.24.0 exec playwright test --config=playwright.oidc.config.ts
```

The browser suite checks discovery and JWKS, signed access-token claims and
issuer/audience/roles, all four RBAC roles, spoofed development headers,
cross-origin mutation rejection, Redis-backed session renewal under concurrent
requests, expiry, SSE, synthetic invoice/PO/receipt extraction, reviewer
confirmation, deterministic matching, review audit actor and logout. It stores
no tokens in localStorage and disables Playwright traces, screenshots and video.
The generated PDFs and Playwright output are ignored by Git. Do not upload
traces or Keycloak database files to an issue or commit them.

When finished, stop the host processes with Ctrl+C. Stop only the opt-in
Keycloak container with `docker compose --profile auth-test stop keycloak` if
the rest of your development stack should keep running. The API and web app
must be restarted in normal development mode to use synthetic local login.

This is a local integration test, not a production deployment validation. It
does not prove TLS, external identity-provider availability, multi-instance
refresh coordination, secret rotation, Redis HA or public-cloud configuration.
