import { describe, expect, it } from "vitest";

import { intakeSchema } from "./page";

const base = {
  createPo: false,
  createReceipt: false,
  poNumber: "",
  vendorName: "",
  currency: "INR",
  description: "",
  quantity: "",
  unitPrice: "",
  receiptNumber: "",
  receivedAt: "",
  receivedQuantity: "",
};

describe("invoice intake validation", () => {
  it("accepts a supported synthetic PDF", () => {
    const invoice = new File(["%PDF-1.7 synthetic"], "synthetic.pdf", { type: "application/pdf" });
    expect(intakeSchema.safeParse({ ...base, invoice }).success).toBe(true);
  });

  it("rejects unsupported files before upload", () => {
    const invoice = new File(["not an invoice"], "notes.txt", { type: "text/plain" });
    expect(intakeSchema.safeParse({ ...base, invoice }).success).toBe(false);
  });
});
