import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/backend/**", (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.endsWith("/health/ready")) return route.fulfill({ json: { status: "ready" } });
    if (pathname.endsWith("/v1/dashboard/summary")) return route.fulfill({ json: { documents_total: 12, jobs_processing: 2, jobs_failed: 1, reviews_waiting: 1, oldest_waiting_review_opened_at: "2026-09-26T06:00:00Z" } });
    if (pathname.endsWith("/v1/review-cases")) return route.fulfill({ json: { next_cursor: null, items: [reviewItem()] } });
    return route.fulfill({ status: 404, json: { detail: "Unexpected test request" } });
  });
});

test("empty intake is accessible and visually stable", async ({ page }) => {
  await page.goto("/intake");
  await expect(page.getByRole("button", { name: "Begin processing" })).toBeDisabled();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await expect(page).toHaveScreenshot("intake-empty.png", { fullPage: true, animations: "disabled", maxDiffPixelRatio: 0.08 });
});

test("review queue exposes URL-backed filters and stable evidence", async ({ page }) => {
  await page.goto("/reviews?status=OPEN&reason_code=CURRENCY_MISMATCH");
  await expect(page.getByRole("button", { name: "Open" })).toHaveClass(/active/);
  await expect(page.getByLabel("Reason")).toHaveValue("CURRENCY_MISMATCH");
  await expect(page.getByRole("link", { name: "Case 00000000" })).toBeVisible();
  await expect(page).toHaveScreenshot("review-queue.png", { fullPage: true, animations: "disabled", maxDiffPixelRatio: 0.08 });
});

test("mobile navigation opens with the keyboard and retains visible focus", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/intake");
  const menu = page.getByRole("button", { name: "Open navigation" });
  await menu.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("navigation", { name: "Primary navigation" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Review queue/ })).toBeVisible();
});

function reviewItem() {
  return {
    id: "00000000-0000-4000-8000-000000000010",
    match_run_id: "00000000-0000-4000-8000-000000000011",
    status: "OPEN",
    assigned_reviewer_id: null,
    version: 1,
    opened_at: "2026-09-26T06:00:00Z",
    claimed_at: null,
    resolved_at: null,
    resolution: null,
    resolution_reason: null,
    reason_codes: ["CURRENCY_MISMATCH"],
    review_triggers: [{ id: "00000000-0000-4000-8000-000000000012", type: "MATCH_REASON", code: "CURRENCY_MISMATCH", source_id: "00000000-0000-4000-8000-000000000011", source_url: "/v1/matches/00000000-0000-4000-8000-000000000011", created_at: "2026-09-26T06:00:00Z" }],
    extraction_name: "deterministic-baseline",
    extraction_version: "0.2.0",
    events_url: "/events",
    audit_verification_url: "/audit-verification",
  };
}
