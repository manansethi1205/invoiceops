# Web console

The Next.js console is a thin client over the versioned FastAPI contract. It does not perform
arithmetic, infer policy, approve an invoice or authorize payment. The backend remains the source
of truth for extraction, matching, risk and review state.

## Product architecture

```text
Browser -> Next.js App Router -> same-origin /api/backend proxy -> FastAPI
   |                                                       |
   +-- TanStack Query reads/mutations                      +-- PostgreSQL state
   +-- resumable SSE timeline                              +-- durable job events
   +-- PDF/image evidence overlays                         +-- normalized evidence
   +-- reviewer expected_version + X-Reviewer-ID           +-- review state machine
```

The UI uses a near-black enterprise palette, controlled blue actions, semantic status colors,
keyboard-visible focus, responsive navigation and reduced-motion fallbacks. App Router loading and
error boundaries cover each primary route. Radix primitives provide accessible modal behavior;
Motion is limited to evidence-overlay transitions.

## Live processing behavior

The job timeline validates every SSE payload with Zod, deduplicates by durable event ID/sequence,
sorts replayed events and reconnects with bounded exponential backoff and `Last-Event-ID`. The
stream ends only on a durable completion/failure event. If a connection closes ambiguously, the
client checks the job-status endpoint before reconnecting. Heartbeats never enter product history.

## Multi-document cases

`/intake` uploads real invoice, purchase-order and receipt/delivery files. It creates one backend
case and attaches each file with stable retry keys; it never chains direct canonical PO or receipt
creation calls. `/cases/{case_id}` keeps the selected document in the URL, shows evidence tabs,
validates role-aware case SSE events with Zod and exposes editable confirmation payloads.

Document roles are chosen by the operator, not automatically classified. Supporting extraction
always requires confirmation. Authentication is still absent, so this workflow must not be
publicly deployed until verified OIDC identity and role-based authorization are added.

## Local development

Start the API stack, then run the web application:

```powershell
Copy-Item .env.example .env
docker compose up --build -d postgres redis object-storage migrate api worker
Set-Location web
corepack enable
pnpm install --frozen-lockfile
pnpm dev
```

Open `http://localhost:3000`. Alternatively, `docker compose up --build` runs the complete stack,
including the web container. Grafana uses `http://localhost:3001` to avoid a port collision.

The Next.js server proxies `/api/backend/*` to `INVOICEOPS_API_URL`; browser code therefore uses a
same-origin API path. Never place provider credentials in `NEXT_PUBLIC_*` variables.

## Contract generation and checks

```powershell
uv run python scripts/export_openapi.py
Set-Location web
pnpm openapi
pnpm typecheck
pnpm lint
pnpm test
pnpm exec playwright install chromium
pnpm test:e2e
```

CI regenerates `openapi.json` and `schema.d.ts` and fails on contract drift. Playwright covers the
product shell with mocked, typed network responses so accessibility and visual checks are stable;
backend behavior remains covered by Python integration and Compose tests. Browser coverage includes
dashboard, empty intake, URL-backed review filters, mobile keyboard navigation, reviewer ownership,
resolution confirmation and stale-version conflicts. Screenshots contain synthetic data only.

The Compose integration job additionally builds the standalone web image, waits for it, and probes
both `/dashboard` and the proxied API readiness endpoint. The production image runs as a non-root
user and contains only the standalone Next.js output and required static assets.

## Accessibility

Every primary workflow is operable by keyboard, focus is visibly styled, navigation has explicit
landmarks, status text does not rely on color alone and live activity uses polite announcements.
Playwright runs axe against stable dashboard and intake states. The document viewer supports arrow
page navigation and `+`/`-` zoom controls, while evidence coordinates remain backend-owned.

## Security and product boundaries

- Only synthetic or de-identified documents belong in development and test environments.
- The document response is private/no-store and does not reveal object-storage keys.
- Error displays use bounded API messages and never render raw HTML.
- `X-Reviewer-ID` is an unverified development identity boundary, not authentication.
- `ACCEPTED_EXCEPTION` records a review outcome and never authorizes payment.
- Evidence boxes use the backend's normalized 0–1 coordinates and retain page/source provenance.
- Live job updates are durable database events. `Last-Event-ID` resumes a disconnected stream;
  heartbeats are ephemeral and carry no document text.

## Current limitations

The supporting-document extractor is deterministic and conservative. It does not infer missing
quantities or financial values, and ambiguous layouts remain unconfirmed. The invoice-only
grounded VLM fallback is not applied to PO or receipt schemas in this slice. The confirmation
editor currently presents the typed JSON contract rather than a field-by-field grid. Production
authentication and authorization are not implemented.
