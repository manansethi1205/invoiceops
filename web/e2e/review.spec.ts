import { expect, test } from "./auth-fixture";

test("unresolved invoice row association can be filtered and explained", async ({ page }) => {
  const reason = "EXTRACTION_ROW_ASSOCIATION_UNRESOLVED";
  const detail = reviewDetail(false);
  detail.reason_codes = [reason];
  detail.review_triggers[0].code = reason;
  let requestedReason: string | null = null;
  await page.route("**/api/backend/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/events")) return route.fulfill({ json: [] });
    if (url.pathname.endsWith("/audit-verification")) return route.fulfill({ json: { valid: true } });
    if (url.pathname.endsWith("/v1/review-cases")) {
      requestedReason = url.searchParams.get("reason_code");
      return route.fulfill({ json: { items: [detail], next_cursor: null } });
    }
    if (url.pathname.includes("/v1/review-cases/")) return route.fulfill({ json: detail });
    return route.fulfill({ status: 404, json: { detail: "Unexpected test request" } });
  });
  await page.goto("/reviews");
  await page.getByLabel("Reason", { exact: true }).selectOption(reason);
  await expect(page).toHaveURL(new RegExp(`reason_code=${reason}`));
  await expect.poll(() => requestedReason).toBe(reason);
  await expect(page.locator("table").getByText("Invoice row association needs review", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Case 00000000" }).click();
  await expect(page.getByText("MATCH_REASON: Invoice row association needs review")).toBeVisible();
  await expect(page.getByText("Extracted cells could not be safely linked", { exact: false })).toBeVisible();
  await expect(page.getByText("It does not authorize payment.", { exact: false }).first()).toBeVisible();
});

test("a reviewer claims an open case under the session identity", async ({ page }) => {
  let claimed = false;
  await page.route("**/api/backend/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname.endsWith("/events")) return route.fulfill({ json: [] });
    if (pathname.endsWith("/audit-verification")) return route.fulfill({ json: { valid: true, errors: [], event_count: 1, last_sequence_number: 1, reconstructed_assignee: claimed ? "reviewer-1" : null, reconstructed_opening_triggers: [], reconstructed_resolution: null, reconstructed_resolution_reason: null, reconstructed_status: claimed ? "CLAIMED" : "OPEN", reconstructed_version: claimed ? 2 : 1, review_case_id: "00000000-0000-4000-8000-000000000010" } });
    if (pathname.endsWith("/claim")) {
      expect(request.postDataJSON()).toEqual({ expected_version: 1 });
      claimed = true;
      return route.fulfill({ json: reviewDetail(true) });
    }
    if (pathname.includes("/v1/review-cases/")) return route.fulfill({ json: reviewDetail(claimed) });
    return route.fulfill({ status: 404, json: { detail: "Unexpected test request" } });
  });

  await page.goto("/reviews/00000000-0000-4000-8000-000000000010");
  await page.getByRole("button", { name: "Claim case" }).click();
  await expect(page.getByText("CLAIMED")).toBeVisible();
});

test("resolution requires confirmation and surfaces stale-version conflicts", async ({ page }) => {
  await page.route("**/api/backend/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname.endsWith("/events")) return route.fulfill({ json: [] });
    if (pathname.endsWith("/audit-verification")) return route.fulfill({ json: { valid: true, errors: [], event_count: 2, last_sequence_number: 2, reconstructed_assignee: "reviewer-1", reconstructed_opening_triggers: [], reconstructed_resolution: null, reconstructed_resolution_reason: null, reconstructed_status: "CLAIMED", reconstructed_version: 2, review_case_id: "00000000-0000-4000-8000-000000000010" } });
    if (pathname.endsWith("/resolve")) {
      expect(request.postDataJSON()).toEqual({ expected_version: 2, resolution: "ACCEPTED_EXCEPTION", reason: "Approved policy exception" });
      return route.fulfill({ status: 409, json: { detail: "Case version conflict" } });
    }
    if (pathname.includes("/v1/review-cases/")) return route.fulfill({ json: reviewDetail(true) });
    return route.fulfill({ status: 404, json: { detail: "Unexpected test request" } });
  });

  await page.goto("/reviews/00000000-0000-4000-8000-000000000010");
  await page.getByLabel("Required explanation").fill("Approved policy exception");
  await page.getByRole("button", { name: "Resolve case" }).click();
  await expect(page.getByRole("dialog", { name: "Confirm case resolution" })).toBeVisible();
  await page.getByRole("button", { name: "Confirm resolution" }).click();
  await expect(page.getByRole("alert")).toContainText("Case version conflict");
  await expect(page.getByRole("dialog", { name: "Confirm case resolution" })).toBeVisible();
});

function reviewDetail(claimed: boolean) {
  return {
    id: "00000000-0000-4000-8000-000000000010",
    match_run_id: "00000000-0000-4000-8000-000000000011",
    status: claimed ? "CLAIMED" : "OPEN",
    assigned_reviewer_id: claimed ? "synthetic-reviewer" : null,
    version: claimed ? 2 : 1,
    opened_at: "2026-09-26T06:00:00Z",
    claimed_at: claimed ? "2026-09-26T06:10:00Z" : null,
    resolved_at: null,
    resolution: null,
    resolution_reason: null,
    reason_codes: ["CURRENCY_MISMATCH"],
    review_triggers: [{ id: "00000000-0000-4000-8000-000000000012", type: "MATCH_REASON", code: "CURRENCY_MISMATCH", source_id: "00000000-0000-4000-8000-000000000011", source_url: "/v1/matches/00000000-0000-4000-8000-000000000011", created_at: "2026-09-26T06:00:00Z" }],
    extraction_name: "deterministic-baseline",
    extraction_version: "0.2.0",
    events_url: "/events",
    audit_verification_url: "/audit-verification",
    match: { document_id: "00000000-0000-4000-8000-000000000013", decision: "NEEDS_REVIEW", risk_disposition: "NEEDS_REVIEW" },
  };
}
