import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./auth-fixture";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/backend/**", (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.endsWith("/health/ready")) return route.fulfill({ json: { status: "ready" } });
    if (pathname.endsWith("/v1/dashboard/summary")) return route.fulfill({ json: { documents_total: 12, jobs_processing: 2, jobs_failed: 1, reviews_waiting: 3, oldest_waiting_review_opened_at: "2026-09-26T06:00:00Z" } });
    if (pathname.endsWith("/v1/invoices")) return route.fulfill({ json: { next_cursor: null, items: [{ document_id: "00000000-0000-4000-8000-000000000001", filename: "synthetic-invoice.pdf", content_type: "application/pdf", byte_size: 1200, created_at: "2026-09-26T06:00:00Z", job_id: "00000000-0000-4000-8000-000000000002", job_status: "succeeded", invoice_number: "SYN-1042", currency: "INR", total: "1250.00", latest_match_run_id: null, match_decision: "NEEDS_REVIEW", review_case_id: null, review_status: "OPEN" }] } });
    return route.fulfill({ status: 404, json: { detail: "Unexpected test request" } });
  });
});

test("dashboard is keyboard-visible, accessible and visually stable", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Invoices moving with evidence" })).toBeVisible();
  await expect(page.getByText("SYN-1042")).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
  await expect(page).toHaveScreenshot("dashboard.png", {
    fullPage: true,
    animations: "disabled",
    maxDiffPixelRatio: 0.03,
  });
});
