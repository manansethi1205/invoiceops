import { readFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";
import { createClient } from "redis";

const api = "/api/backend";
const caseIdPattern = /^[0-9a-f-]{36}$/i;
type Role = "operator" | "reviewer" | "auditor" | "admin";

test("real authorization-code token has the API contract claims", async ({ page }) => {
  let callbackUrl: URL | undefined;
  await page.route("**/realms/invoiceops/login-actions/authenticate**", async (route) => {
    const response = await route.fetch({ maxRedirects: 0 });
    const location = response.headers()["location"];
    if (response.status() !== 302 || !location) throw new Error("Synthetic login did not issue a code redirect");
    callbackUrl = new URL(location);
    await route.fulfill({ status: 200, body: "Synthetic token-shape check complete" });
  });
  await page.goto("/login");
  await page.getByRole("link", { name: "Sign in with identity provider" }).click();
  await page.locator("#username").fill("reviewer");
  await page.locator("#password").fill("LocalOnly-User-ChangeMe123!");
  await page.locator("#kc-login").click();
  await expect.poll(() => callbackUrl?.searchParams.get("code")).toBeTruthy();
  const state = callbackUrl?.searchParams.get("state");
  const code = callbackUrl?.searchParams.get("code");
  if (!state || !code) throw new Error("OIDC authorization callback is incomplete");
  const redis = createClient({ url: process.env.AUTH_SESSION_REDIS_URL ?? "redis://127.0.0.1:6379/1" });
  await redis.connect();
  let verifier: string;
  try {
    const raw = await redis.get(`invoiceops:login:${state}`);
    if (!raw) throw new Error("OIDC login state missing");
    verifier = (JSON.parse(raw) as { verifier: string }).verifier;
  } finally {
    await redis.quit();
  }
  const token = await page.request.post("http://localhost:8080/realms/invoiceops/protocol/openid-connect/token", {
    form: {
      grant_type: "authorization_code", client_id: "invoiceops-web",
      client_secret: "LocalOnly-Web-Client-NotAProductionSecret",
      redirect_uri: "http://127.0.0.1:3000/api/auth/callback", code, code_verifier: verifier,
    },
  });
  expect(token.status()).toBe(200);
  const body = await token.json() as { access_token: string };
  const claims = JSON.parse(Buffer.from(body.access_token.split(".")[1], "base64url").toString("utf8")) as Record<string, unknown>;
  expect(claims.iss).toBe("http://localhost:8080/realms/invoiceops");
  expect(claims.sub).toBeTruthy();
  expect(claims.roles).toEqual(["reviewer"]);
  expect(typeof claims.exp).toBe("number");
  expect(typeof claims.nbf).toBe("number");
  expect(claims.aud).toContain("invoiceops-api");
  // Only report the API status, not bearer token bytes.
  const principal = await page.request.get("http://127.0.0.1:8000/v1/me", {
    headers: { authorization: `Bearer ${body.access_token}` },
  });
  expect(principal.status()).toBe(200);
});

async function signIn(page: Page, role: Role): Promise<{ subject: string; roles: string[] }> {
  await page.goto("/login");
  await page.getByRole("link", { name: "Sign in with identity provider" }).click();
  await expect(page).toHaveURL(/localhost:8080\/realms\/invoiceops/);
  await page.locator("#username").fill(role);
  await page.locator("#password").fill("LocalOnly-User-ChangeMe123!");
  await page.locator("#kc-login").click();
  await expect(page).toHaveURL(/127\.0\.0\.1:3000\/dashboard/);
  const response = await page.request.get(`${api}/v1/me`);
  expect(response.status()).toBe(200);
  const principal = await response.json() as { subject: string; roles: string[] };
  expect(principal.roles).toEqual([role]);
  expect(principal.subject).toBeTruthy();
  return principal;
}

async function jsonPost(page: Page, path: string, body: unknown) {
  return page.request.post(`${api}${path}`, {
    data: body,
    headers: { origin: "http://127.0.0.1:3000" },
  });
}

test("real provider claims enforce all four roles and ignore spoofed development identity", async ({ browser }) => {
  for (const role of ["operator", "reviewer", "auditor", "admin"] as const) {
    const context = await browser.newContext();
    try {
      const page = await context.newPage();
      const principal = await signIn(page, role);
      const spoofed = await page.request.get(`${api}/v1/me`, {
        headers: { "X-Actor-ID": "forged", "X-Reviewer-ID": "forged", "X-Dev-Roles": "admin" },
      });
      expect((await spoofed.json() as { subject: string }).subject).toBe(principal.subject);
      const create = await jsonPost(page, "/v1/cases", { idempotency_key: `oidc-role-${role}-${randomUUID()}` });
      expect(create.status()).toBe(role === "auditor" ? 403 : 201);
      const read = await page.request.get(`${api}/v1/cases/00000000-0000-4000-8000-000000000001`);
      expect(read.status()).toBe(404);
      const reviewQueue = await page.request.get(`${api}/v1/review-cases`);
      expect(reviewQueue.status()).toBe(role === "operator" ? 403 : 200);
      const claim = await jsonPost(page, "/v1/review-cases/00000000-0000-4000-8000-000000000001/claim", { expected_version: 1 });
      expect(claim.status()).toBe(role === "reviewer" || role === "admin" ? 404 : 403);
      const confirm = await jsonPost(page, "/v1/cases/00000000-0000-4000-8000-000000000001/purchase-order/confirm", {
        expected_case_version: 1,
        extraction_run_id: "00000000-0000-4000-8000-000000000002",
        extractor_version: "synthetic-test",
        idempotency_key: randomUUID(),
        confirmed: {
          external_po_number: "PO-SYN-ROLE", currency: "INR",
          lines: [{ line_number: "1", description: "Synthetic item", ordered_quantity: "1", unit_price: "1.00" }],
        },
      });
      expect(confirm.status()).toBe(role === "reviewer" || role === "admin" ? 409 : 403);
      if (role === "auditor") {
        const upload = await page.request.post(`${api}/v1/invoices`, {
          headers: { origin: "http://127.0.0.1:3000" },
          multipart: { file: { name: "synthetic.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 synthetic") } },
        });
        expect(upload.status()).toBe(403);
      }
      const foreign = await page.request.post(`${api}/v1/cases`, {
        data: { idempotency_key: randomUUID() },
        headers: { origin: "https://foreign.example" },
      });
      expect(foreign.status()).toBe(403);
      await page.getByRole("button", { name: "Sign out" }).click();
      await expect(page).toHaveURL(/\/login/);
      expect((await page.request.get(`${api}/v1/me`)).status()).toBe(401);
    } finally {
      await context.close();
    }
  }
});

test("reviewer processes a synthetic three-document case with verified identity", async ({ page }) => {
  const principal = await signIn(page, "reviewer");
  const created = await jsonPost(page, "/v1/cases", { idempotency_key: `oidc-case-${randomUUID()}` });
  expect(created.status()).toBe(201);
  const payableCase = await created.json() as { id: string; version: number };
  expect(payableCase.id).toMatch(caseIdPattern);

  async function currentCase() {
    const response = await page.request.get(`${api}/v1/cases/${payableCase.id}`);
    expect(response.status()).toBe(200);
    return response.json() as Promise<{ version: number; status: string }>;
  }

  async function attach(role: string, fileName: string) {
    const body = await readFile(new URL(`../../tmp/oidc-smoke/${fileName}`, import.meta.url));
    const response = await page.request.post(`${api}/v1/cases/${payableCase.id}/documents`, {
      headers: { origin: "http://127.0.0.1:3000" },
      multipart: {
        file: { name: fileName, mimeType: "application/pdf", buffer: body },
        role, idempotency_key: `oidc-${role}-${randomUUID()}`,
        expected_case_version: String((await currentCase()).version),
      },
    });
    expect(response.status()).toBe(202);
    return response.json() as Promise<{ attachment: { document_id: string; job_id: string } }>;
  }

  async function extraction(documentId: string) {
    let found: { id: string; document_id: string; status: string; extractor_version: string } | undefined;
    await expect.poll(async () => {
      const response = await page.request.get(`${api}/v1/cases/${payableCase.id}/extractions`);
      expect(response.status()).toBe(200);
      const runs = await response.json() as Array<typeof found>;
      found = runs.find((run) => run?.document_id === documentId);
      return found?.status;
    }, { timeout: 45_000, intervals: [500, 1000, 2000] }).toBe("SUCCEEDED");
    if (!found) throw new Error("Synthetic supporting extraction missing");
    return found;
  }

  const invoice = await attach("INVOICE", "invoice.pdf");
  await expect.poll(async () => {
    const response = await page.request.get(`${api}/v1/jobs/${invoice.attachment.job_id}`);
    return (await response.json() as { status: string }).status;
  }, { timeout: 45_000 }).toBe("succeeded");
  const stream = await page.evaluate(async (jobId) => {
    const controller = new AbortController();
    const response = await fetch(`/api/backend/v1/jobs/${jobId}/events`, {
      headers: { accept: "text/event-stream" }, signal: controller.signal,
    });
    const chunk = await response.body?.getReader().read();
    controller.abort();
    return { status: response.status, received: Boolean(chunk?.value?.length) };
  }, invoice.attachment.job_id);
  expect(stream).toEqual({ status: 200, received: true });
  const po = await attach("PURCHASE_ORDER", "po.pdf");
  const poRun = await extraction(po.attachment.document_id);
  await page.goto(`/cases/${payableCase.id}?document=${po.attachment.document_id}`);
  await expect(page.getByRole("heading", { name: "Human confirmation" })).toBeVisible();
  await page.getByRole("button", { name: "View evidence for PO number" }).click();
  await expect(page.locator(".document-panel .evidence-box.active")).toBeVisible();
  await expect(page.getByLabel("Document PDF viewer")).toBeFocused();

  const poConfirmation = await jsonPost(page, `/v1/cases/${payableCase.id}/purchase-order/confirm`, {
    expected_case_version: (await currentCase()).version,
    extraction_run_id: poRun.id,
    extractor_version: poRun.extractor_version,
    idempotency_key: `oidc-confirm-po-${randomUUID()}`,
    correction_reason: "Synthetic printed amount discrepancy for review routing",
    confirmed: {
      external_po_number: "PO-OIDC-WALKTHROUGH", vendor_name: "Synthetic Compose Vendor",
      buyer_name: "Example Company", currency: "INR", issue_date: "2026-09-19",
      subtotal: "1200.00", tax: "216.00", total: "1416.00",
      lines: [
        { line_number: "1", description: "Industrial Filter", ordered_quantity: "2", unit_price: "500.00", line_total: "1001.00" },
        { line_number: "2", description: "Mounting Bracket", ordered_quantity: "4", unit_price: "50.00", line_total: "200.00" },
      ],
    },
  });
  expect(poConfirmation.status()).toBe(200);

  const receipt = await attach("GOODS_RECEIPT", "receipt.pdf");
  const receiptRun = await extraction(receipt.attachment.document_id);
  const receiptConfirmation = await jsonPost(page, `/v1/cases/${payableCase.id}/receipts/${receipt.attachment.document_id}/confirm`, {
    expected_case_version: (await currentCase()).version,
    extraction_run_id: receiptRun.id,
    extractor_version: receiptRun.extractor_version,
    idempotency_key: `oidc-confirm-receipt-${randomUUID()}`,
    correction_reason: "Synthetic PO line association confirmed by reviewer",
    confirmed: {
      external_receipt_number: "GR-OIDC-WALKTHROUGH", referenced_po_number: "PO-OIDC-WALKTHROUGH",
      supplier: "Synthetic Compose Vendor", received_at: "2026-09-19T12:00:00Z",
      lines: [
        { purchase_order_line_number: "1", description: "Industrial Filter", received_quantity: "2", accepted_quantity: "2", rejected_quantity: "0" },
        { purchase_order_line_number: "2", description: "Mounting Bracket", received_quantity: "4", accepted_quantity: "4", rejected_quantity: "0" },
      ],
    },
  });
  expect(receiptConfirmation.status()).toBe(200);
  expect((await currentCase()).status).toBe("READY_TO_MATCH");
  const match = await jsonPost(page, `/v1/cases/${payableCase.id}/match`, {
    expected_case_version: (await currentCase()).version, idempotency_key: `oidc-match-${randomUUID()}`,
  });
  expect(match.status()).toBe(200);
  const matched = await match.json() as { id: string; decision: string; matching_mode: string };
  expect(matched.matching_mode).toBe("THREE_WAY");
  expect(matched.decision).toBe("NEEDS_REVIEW");
  const reviews = await page.request.get(`${api}/v1/review-cases?limit=100`);
  expect(reviews.status()).toBe(200);
  const listed = await reviews.json() as { items: Array<{ id: string; match_run_id: string; version: number }> };
  const review = listed.items.find((item) => item.match_run_id === matched.id);
  expect(review).toBeDefined();
  if (!review) return;
  await page.goto(`/reviews/${review.id}`);
  await expect(page.getByRole("button", { name: "Claim case" })).toBeVisible();
  const claim = await jsonPost(page, `/v1/review-cases/${review.id}/claim`, { expected_version: review.version });
  expect(claim.status()).toBe(200);
  const events = await page.request.get(`${api}/v1/review-cases/${review.id}/events`);
  expect(events.status()).toBe(200);
  const audit = await events.json() as Array<{ event_type: string; actor_id: string }>;
  expect(audit.find((event) => event.event_type === "CASE_CLAIMED")?.actor_id).toBe(principal.subject);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
});

test("rotating refresh tokens survive concurrent proxy requests and expired sessions fail closed", async ({ page }) => {
  const principal = await signIn(page, "reviewer");
  const sessionCookie = (await page.context().cookies()).find((cookie) => cookie.name === "invoiceops_session");
  expect(sessionCookie).toBeDefined();
  if (!sessionCookie) return;
  const redis = createClient({ url: process.env.AUTH_SESSION_REDIS_URL ?? "redis://localhost:6379/1" });
  await redis.connect();
  try {
    const key = `invoiceops:session:${sessionCookie.value}`;
    const raw = await redis.get(key);
    expect(raw).toBeTruthy();
    if (!raw) return;
    const stored = JSON.parse(raw) as {
      subject: string; roles: string[]; accessToken: string; refreshToken: string; expiresAt: number;
    };
    expect(Boolean(stored.refreshToken)).toBe(true);
    const discovery = await page.request.get("http://localhost:8080/realms/invoiceops/.well-known/openid-configuration");
    expect(discovery.status()).toBe(200);
    const metadata = await discovery.json() as { issuer: string; jwks_uri: string };
    expect(metadata.issuer).toBe("http://localhost:8080/realms/invoiceops");
    const jwks = await page.request.get(metadata.jwks_uri);
    expect(jwks.status()).toBe(200);
    expect((await jwks.json() as { keys: unknown[] }).keys.length).toBeGreaterThan(0);
    const claims = JSON.parse(Buffer.from(stored.accessToken.split(".")[1], "base64url").toString("utf8")) as {
      iss: string; aud: string | string[]; sub: string; roles: string[]; exp: number; nbf: number;
    };
    expect(claims.iss).toBe(metadata.issuer);
    expect(Array.isArray(claims.aud) ? claims.aud.includes("invoiceops-api") : claims.aud === "invoiceops-api").toBe(true);
    expect(claims.sub).toBe(principal.subject);
    expect(claims.roles).toEqual(["reviewer"]);
    expect(claims.exp > claims.nbf).toBe(true);
    const previousAccess = stored.accessToken;
    const previousRefresh = stored.refreshToken;
    await redis.set(key, JSON.stringify({ ...stored, expiresAt: Date.now() + 1_000 }), { EX: 300 });
    const responses = await Promise.all([
      page.request.get(`${api}/v1/me`),
      page.request.get(`${api}/v1/me`),
    ]);
    expect(responses.map((response) => response.status())).toEqual([200, 200]);
    for (const response of responses) {
      expect((await response.json() as { subject: string }).subject).toBe(principal.subject);
    }
    const renewedRaw = await redis.get(key);
    expect(renewedRaw).toBeTruthy();
    if (!renewedRaw) return;
    const renewed = JSON.parse(renewedRaw) as typeof stored;
    // Compare only booleans so assertion output never discloses token values.
    expect(renewed.accessToken !== previousAccess).toBe(true);
    expect(renewed.refreshToken !== previousRefresh).toBe(true);
    await redis.del(key);
    expect((await page.request.get("/api/auth/session")).status()).toBe(401);
    expect((await page.request.get(`${api}/v1/me`)).status()).toBe(401);
  } finally {
    await redis.quit();
  }
});
