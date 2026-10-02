import { describe, expect, it } from "vitest";

import {
  amountMismatch, backendIssues, calculatedAmount, purchaseOrderFormSchema, purchaseOrderPayload, receiptFormSchema, sameOptionalDecimal,
  type PurchaseOrderForm, type ReceiptForm,
} from "./confirmation";

const purchaseOrder: PurchaseOrderForm = {
  external_po_number: "PO-SYN-42", vendor_name: "Synthetic Supplier", buyer_name: "Example Buyer",
  issue_date: "2026-09-30", currency: "INR", subtotal: "100.00", tax: "18.00", total: "118.00",
  lines: [{ line_number: "1", description: "Widgets", ordered_quantity: "2", unit_price: "50.00", line_total: "100.00" }],
  correction_reason: "",
};
const receipt: ReceiptForm = {
  external_receipt_number: "GR-SYN-42", referenced_po_number: "PO-SYN-42",
  received_at: "2026-09-30T00:00", supplier: "Synthetic Supplier",
  lines: [{ purchase_order_line_number: "1", description: "Widgets", received_quantity: "2", accepted_quantity: "2", rejected_quantity: "0" }],
  correction_reason: "",
};

describe("supporting-document confirmation validation", () => {
  it("accepts unchanged typed values and never converts financial inputs to floats", () => {
    expect(purchaseOrderFormSchema.safeParse(purchaseOrder).success).toBe(true);
    expect(receiptFormSchema.safeParse(receipt).success).toBe(true);
    expect(calculatedAmount("1.25", "19.99")).toBe("24.9875");
    expect(amountMismatch("24.99", "1.25", "19.99")).toBe(true);
    expect(amountMismatch("100.00", "2", "50.00")).toBe(false);
    expect(sameOptionalDecimal("20.00", "20")).toBe(true);
    expect(sameOptionalDecimal(null, "")).toBe(true);
    expect(sameOptionalDecimal("20.00", "21")).toBe(false);
    expect(purchaseOrderPayload({ ...purchaseOrder, lines: [{ ...purchaseOrder.lines[0], line_total: "" }] }).lines[0].line_total).toBeNull();
  });

  it("attaches invalid values to their individual fields", () => {
    const invalid = purchaseOrderFormSchema.safeParse({ ...purchaseOrder, currency: "inr", issue_date: "2026-02-30", lines: [{ ...purchaseOrder.lines[0], ordered_quantity: "-1" }] });
    expect(invalid.success).toBe(false);
    if (!invalid.success) expect(invalid.error.issues.map((issue) => issue.path.join("."))).toEqual(expect.arrayContaining(["currency", "issue_date", "lines.0.ordered_quantity"]));
  });

  it("requires received quantity to equal accepted plus rejected", () => {
    const invalid = receiptFormSchema.safeParse({ ...receipt, lines: [{ ...receipt.lines[0], accepted_quantity: "1" }] });
    expect(invalid.success).toBe(false);
    if (!invalid.success) expect(invalid.error.issues[0].path.join(".")).toBe("lines.0.accepted_quantity");
  });

  it("maps backend 422 locations without exposing input values", () => {
    expect(backendIssues([{ loc: ["body", "confirmed", "lines", 0, "description"], msg: "Too long", input: "private content" }])).toEqual([{ path: "lines.0.description", message: "Too long" }]);
  });
});
