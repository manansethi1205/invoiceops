import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "./auth-fixture";

const caseId = "00000000-0000-4000-8000-000000000101";
const documentId = "00000000-0000-4000-8000-000000000102";
const attachmentId = "00000000-0000-4000-8000-000000000103";
const extractionId = "00000000-0000-4000-8000-000000000104";
const transparentPng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  "base64",
);

test("processing case preserves role-aware document state", async ({ page }) => {
  await mockCase(page, "PROCESSING", false, false);
  await page.goto(`/cases/${caseId}?document=${documentId}`);

  await expect(page.getByRole("banner")).toContainText("InvoiceOps / Payable case");
  await expect(page.getByText("PROCESSING", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Run case match" })).toBeDisabled();
  await expect(page).toHaveScreenshot("case-processing.png", screenshotOptions);
});

test("supporting evidence requires accessible human confirmation", async ({ page }) => {
  await mockCase(page, "NEEDS_CONFIRMATION", true, false);
  await page.goto(`/cases/${caseId}?document=${documentId}`);

  await expect(page.getByRole("banner")).toContainText("InvoiceOps / Payable case");
  await expect(page.getByRole("heading", { name: "Human confirmation" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "PO number" })).toHaveValue("PO-SYN-42");
  await expect(page.getByRole("table")).toContainText("Widgets");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.addStyleTag({ content: ".topbar { position: static !important; }" });
  await expect(page.getByLabel("Purchase order confirmation")).toHaveScreenshot("case-confirmation.png", screenshotOptions);
  const lineTable = page.locator(".confirmation-table-scroll");
  await lineTable.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
  await expect(lineTable).toHaveScreenshot("po-line-amount.png", screenshotOptions);
});

test("matched case remains evidence-linked and non-authorizing", async ({ page }) => {
  await mockCase(page, "MATCHED", true, true);
  await page.goto(`/cases/${caseId}?document=${documentId}`);

  await expect(page.getByRole("banner")).toContainText("InvoiceOps / Payable case");
  await expect(page.getByText("MATCHED", { exact: true })).toBeVisible();
  await expect(page.getByText(/no result authorizes payment/i)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Human confirmation" })).toHaveCount(0);
  await expect(page).toHaveScreenshot("case-matched.png", screenshotOptions);
});

test("matching retries send the original idempotency key", async ({ page }) => {
  await mockCase(page, "READY_TO_MATCH", true, true);
  const keys: string[] = [];
  await page.route(`**/api/backend/v1/cases/${caseId}/match`, async (route) => {
    const body = route.request().postDataJSON() as { idempotency_key: string };
    keys.push(body.idempotency_key);
    await route.fulfill(keys.length === 1
      ? { status: 503, json: { detail: "Temporary failure" } }
      : { json: {} });
  });
  await page.goto(`/cases/${caseId}?document=${documentId}`);
  await page.getByRole("button", { name: "Run case match" }).click();
  await expect(page.locator(".field-error")).toBeVisible();
  await page.getByRole("button", { name: "Run case match" }).click();
  await expect.poll(() => keys.length).toBe(2);
  expect(keys[0]).toBeTruthy();
  expect(keys[1]).toBe(keys[0]);
});

test("confirmation retries send the original idempotency key", async ({ page }) => {
  await mockCase(page, "NEEDS_CONFIRMATION", true, false);
  const keys: string[] = [];
  await page.route(`**/api/backend/v1/cases/${caseId}/purchase-order/confirm`, async (route) => {
    const body = route.request().postDataJSON() as { idempotency_key: string };
    keys.push(body.idempotency_key);
    await route.fulfill(keys.length === 1
      ? { status: 503, json: { detail: "Temporary failure" } }
      : { json: {} });
  });
  await page.goto(`/cases/${caseId}?document=${documentId}`);
  await page.getByRole("button", { name: "Confirm canonical record" }).click();
  await expect(page.locator(".field-error")).toBeVisible();
  await page.getByRole("button", { name: "Confirm canonical record" }).click();
  await expect.poll(() => keys.length).toBe(2);
  expect(keys[0]).toBeTruthy();
  expect(keys[1]).toBe(keys[0]);
});

test("unchanged purchase order confirms without a correction reason", async ({ page }) => {
  await mockCase(page, "NEEDS_CONFIRMATION", true, false);
  let submitted: { correction_reason: string | null; confirmed: { lines: { line_total: string | null }[] } } | undefined;
  await page.route(`**/api/backend/v1/cases/${caseId}/purchase-order/confirm`, async (route) => {
    submitted = route.request().postDataJSON() as typeof submitted;
    await route.fulfill({ json: {} });
  });
  await page.goto(`/cases/${caseId}?document=${documentId}`);
  await expect(page.getByLabel("Confirmation summary")).toContainText("0 fields changed");
  await page.getByRole("button", { name: "Confirm canonical record" }).click();
  await expect.poll(() => submitted).toBeTruthy();
  expect(submitted?.correction_reason).toBeNull();
  expect(submitted?.confirmed.lines[0].line_total).toBe("100.00");
});

test("equivalent decimal formatting does not count as a PO amount correction", async ({ page }) => {
  await mockCase(page, "NEEDS_CONFIRMATION", true, false);
  let submitted: { correction_reason: string | null; confirmed: { lines: { line_total: string | null }[] } } | undefined;
  await page.route(`**/api/backend/v1/cases/${caseId}/purchase-order/confirm`, async (route) => {
    submitted = route.request().postDataJSON() as typeof submitted;
    await route.fulfill({ json: {} });
  });
  await page.goto(`/cases/${caseId}?document=${documentId}`);
  await page.getByRole("textbox", { name: "Line 1 amount" }).fill("100");
  await expect(page.getByLabel("Confirmation summary")).toContainText("0 fields changed");
  await page.getByRole("button", { name: "Confirm canonical record" }).click();
  await expect.poll(() => submitted).toBeTruthy();
  expect(submitted?.correction_reason).toBeNull();
  expect(submitted?.confirmed.lines[0].line_total).toBe("100");
});

test("corrections and line edits require a reason and keep the same key on retry", async ({ page }) => {
  await mockCase(page, "NEEDS_CONFIRMATION", true, false);
  const keys: string[] = [];
  await page.route(`**/api/backend/v1/cases/${caseId}/purchase-order/confirm`, async (route) => {
    keys.push((route.request().postDataJSON() as { idempotency_key: string }).idempotency_key);
    await route.fulfill({ status: 503, json: { detail: "Temporary failure" } });
  });
  await page.goto(`/cases/${caseId}?document=${documentId}`);
  await page.getByRole("textbox", { name: "Supplier name" }).fill("Corrected Synthetic Supplier");
  await page.getByRole("textbox", { name: "Line 1 amount" }).fill("101.00");
  await expect(page.getByText(/Confirmed amount differs from calculated amount/)).toBeVisible();
  await page.getByRole("button", { name: "Add line item" }).click();
  await page.getByRole("textbox", { name: "Line 2 number" }).fill("2");
  await page.getByRole("textbox", { name: "Line 2 description" }).fill("Additional widgets");
  await page.getByRole("textbox", { name: "Line 2 quantity" }).fill("1");
  await page.getByRole("textbox", { name: "Line 2 unit price" }).fill("10.00");
  await expect(page.getByLabel("Confirmation summary")).toContainText("1 line items added");
  await page.getByRole("button", { name: "Confirm canonical record" }).click();
  await expect(page.getByText("Explain the correction before confirming")).toBeVisible();
  expect(keys).toHaveLength(0);
  await page.getByRole("textbox", { name: /Correction reason/ }).fill("Verified against signed order");
  await page.getByRole("button", { name: "Confirm canonical record" }).click();
  await expect.poll(() => keys.length).toBe(1);
  await page.getByRole("button", { name: "Confirm canonical record" }).click();
  await expect.poll(() => keys.length).toBe(2);
  expect(keys[0]).toBe(keys[1]);
  await page.getByRole("textbox", { name: "Line 2 unit price" }).fill("11.00");
  await page.getByRole("button", { name: "Confirm canonical record" }).click();
  await expect.poll(() => keys.length).toBe(3);
  expect(keys[2]).not.toBe(keys[1]);
});

test("evidence is selectable with keyboard and backend 422 maps to a field", async ({ page }) => {
  await mockCase(page, "NEEDS_CONFIRMATION", true, false);
  await page.route(`**/api/backend/v1/cases/${caseId}/purchase-order/confirm`, async (route) => {
    await route.fulfill({ status: 422, json: { detail: [{ loc: ["body", "confirmed", "currency"], msg: "Currency is not allowed" }] } });
  });
  await page.goto(`/cases/${caseId}?document=${documentId}`);
  const evidence = page.getByRole("button", { name: "View evidence for PO number" });
  await evidence.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator(".document-panel .evidence-box.active")).toBeVisible();
  await expect(page.getByLabel("Document image viewer")).toBeFocused();
  await page.getByRole("button", { name: "Confirm canonical record" }).click();
  await expect(page.getByText("Currency is not allowed")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Currency" })).toHaveAttribute("aria-invalid", "true");
});

test("stale confirmation blocks resubmission until the case is reloaded", async ({ page }) => {
  await mockCase(page, "NEEDS_CONFIRMATION", true, false);
  let attempts = 0;
  await page.route(`**/api/backend/v1/cases/${caseId}/purchase-order/confirm`, async (route) => {
    attempts += 1;
    await route.fulfill({ status: 409, json: { detail: { code: "STALE_CASE_VERSION", message: "Version changed" } } });
  });
  await page.goto(`/cases/${caseId}?document=${documentId}`);
  await page.getByRole("button", { name: "Confirm canonical record" }).click();
  await expect(page.getByText("The case changed during confirmation.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirm canonical record" })).toBeDisabled();
  await page.getByRole("button", { name: "Reload latest case" }).click();
  await expect(page.getByRole("button", { name: "Confirm canonical record" })).toBeEnabled();
  expect(attempts).toBe(1);
});

test("receipt editor validates quantities and fits a narrow viewport", async ({ page }) => {
  await mockCase(page, "NEEDS_CONFIRMATION", true, false);
  await page.route(`**/api/backend/v1/cases/${caseId}/documents`, async (route) => route.fulfill({ json: [{ ...caseDocument("NEEDS_CONFIRMATION", false), role: "GOODS_RECEIPT" }] }));
  await page.route(`**/api/backend/v1/cases/${caseId}/extractions`, async (route) => route.fulfill({ json: [receiptExtraction()] }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/cases/${caseId}?document=${documentId}`);
  await expect(page.getByRole("heading", { name: "Human confirmation" })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Receipt number" })).toHaveValue("GR-SYN-42");
  await page.getByRole("textbox", { name: "Line 1 PO reference" }).fill("1");
  await page.getByRole("textbox", { name: "Line 1 accepted" }).fill("1");
  await page.getByRole("button", { name: "Confirm canonical record" }).click();
  await expect(page.getByText("Accepted plus rejected must equal received")).toBeVisible();
  await page.addStyleTag({ content: ".topbar { position: static !important; }" });
  await expect(page.getByLabel("Receipt confirmation")).toHaveScreenshot("receipt-confirmation-mobile.png", screenshotOptions);
});

test("receipt confirmation has a stable evidence-linked desktop layout", async ({ page }) => {
  await mockCase(page, "NEEDS_CONFIRMATION", true, false);
  await page.route(`**/api/backend/v1/cases/${caseId}/documents`, async (route) => route.fulfill({ json: [{ ...caseDocument("NEEDS_CONFIRMATION", false), role: "GOODS_RECEIPT" }] }));
  await page.route(`**/api/backend/v1/cases/${caseId}/extractions`, async (route) => route.fulfill({ json: [receiptExtraction()] }));
  await page.goto(`/cases/${caseId}?document=${documentId}`);
  await expect(page.getByRole("heading", { name: "Human confirmation" })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.addStyleTag({ content: ".topbar { position: static !important; }" });
  await expect(page.getByLabel("Receipt confirmation")).toHaveScreenshot("receipt-confirmation.png", screenshotOptions);
});

const screenshotOptions = {
  fullPage: false,
  animations: "disabled" as const,
  maxDiffPixelRatio: 0.08,
};

async function mockCase(
  page: Page,
  status: "PROCESSING" | "NEEDS_CONFIRMATION" | "READY_TO_MATCH" | "MATCHED",
  extracted: boolean,
  confirmed: boolean,
) {
  await page.route("**/api/backend/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname.endsWith(`/v1/cases/${caseId}`)) {
      return route.fulfill({ json: payableCase(status) });
    }
    if (pathname.endsWith(`/v1/cases/${caseId}/documents`)) {
      return route.fulfill({ json: [caseDocument(status, confirmed)] });
    }
    if (pathname.endsWith(`/v1/cases/${caseId}/extractions`)) {
      return route.fulfill({ json: extracted ? [purchaseOrderExtraction()] : [] });
    }
    if (pathname.endsWith(`/v1/cases/${caseId}/events`)) {
      const event = {
        id: "00000000-0000-4000-8000-000000000105",
        case_id: caseId,
        sequence: 1,
        event_type: extracted ? "EXTRACTION_COMPLETED" : "UPLOAD_ACCEPTED",
        stage: extracted ? "extraction" : "upload",
        status: extracted ? "completed" : "started",
        message: extracted ? "Purchase-order extraction completed" : "Purchase order uploaded",
        document_id: documentId,
        document_role: "PURCHASE_ORDER",
        payload: {},
        occurred_at: "2026-09-30T08:00:00Z",
      };
      return route.fulfill({
        contentType: "text/event-stream",
        body: `id: 1\nevent: ${event.event_type}\ndata: ${JSON.stringify(event)}\n\n`,
      });
    }
    if (pathname.endsWith(`/v1/documents/${documentId}/content`)) {
      return route.fulfill({ contentType: "image/png", body: transparentPng });
    }
    if (pathname.endsWith("/health/ready")) {
      return route.fulfill({ json: { status: "ready" } });
    }
    return route.fulfill({ status: 404, json: { detail: "Unexpected test request" } });
  });
}

function payableCase(status: string) {
  return {
    id: caseId,
    case_number: "CASE-20260930-SYNTHETIC",
    status,
    version: 4,
    created_at: "2026-09-30T07:55:00Z",
    updated_at: "2026-09-30T08:00:00Z",
  };
}

function caseDocument(status: string, confirmed: boolean) {
  return {
    id: attachmentId,
    case_id: caseId,
    document_id: documentId,
    job_id: "00000000-0000-4000-8000-000000000106",
    role: "PURCHASE_ORDER",
    filename: "synthetic-purchase-order.png",
    content_type: "image/png",
    byte_size: transparentPng.length,
    attachment_order: 1,
    supersedes_id: null,
    is_active: true,
    job_status: status === "PROCESSING" ? "PROCESSING" : "succeeded",
    extraction_status: status === "PROCESSING" ? "PROCESSING" : "SUCCEEDED",
    confirmation_status: confirmed ? "CONFIRMED" : "PENDING",
    created_at: "2026-09-30T07:55:00Z",
  };
}

function field(value: unknown, text: string) {
  return {
    value,
    status: "extracted",
    rule_id: "purchase_order.synthetic.v1",
    evidence: [
      {
        page: 0,
        bbox: { x0: 0.1, y0: 0.1, x1: 0.35, y1: 0.15 },
        text,
        source: "embedded",
      },
    ],
  };
}

function purchaseOrderExtraction() {
  return {
    id: extractionId,
    document_id: documentId,
    role: "PURCHASE_ORDER",
    extractor_name: "deterministic-supporting-documents",
    extractor_version: "0.1.0",
    schema_version: "1.0",
    status: "SUCCEEDED",
    output: {
      po_number: field("PO-SYN-42", "PO-SYN-42"),
      issue_date: field("2026-09-30", "30/09/2026"),
      vendor: field("Synthetic Supplier", "Synthetic Supplier"),
      buyer: field("Example Buyer", "Example Buyer"),
      currency: field("INR", "INR"),
      subtotal: field("100.00", "100.00"),
      tax: field("18.00", "18.00"),
      total: field("118.00", "118.00"),
      line_items: [{
        line_number: field("1", "1"),
        description: field("Widgets", "Widgets"),
        ordered_quantity: field("2", "2"),
        unit_price: field("50.00", "50.00"),
        line_total: field("100.00", "100.00"),
      }],
    },
    used_ocr: false,
    latency_ms: 4.2,
    error_code: null,
    created_at: "2026-09-30T07:56:00Z",
    completed_at: "2026-09-30T07:56:01Z",
  };
}

function receiptExtraction() {
  return {
    ...purchaseOrderExtraction(),
    role: "GOODS_RECEIPT",
    output: {
      receipt_number: field("GR-SYN-42", "GR-SYN-42"),
      referenced_po_number: field("PO-SYN-42", "PO-SYN-42"),
      received_date: field("2026-09-30", "30/09/2026"),
      supplier: field("Synthetic Supplier", "Synthetic Supplier"),
      line_items: [{
        description: field("Widgets", "Widgets"),
        received_quantity: field("2", "2"),
        accepted_quantity: field("2", "2"),
        rejected_quantity: field("0", "0"),
      }],
    },
  };
}
