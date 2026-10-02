import { z } from "zod";

import type { ApiSchema } from "@/lib/api/client";

export type PurchaseOrderExtract = ApiSchema<"ExtractedPurchaseOrder">;
export type ReceiptExtract = ApiSchema<"ExtractedGoodsReceipt">;
export type ExtractedCell = ApiSchema<"ExtractedField_str_"> | ApiSchema<"ExtractedField_date_"> | ApiSchema<"ExtractedField_Decimal_">;

const identifier = z.string().trim().min(1, "Required");
const optionalText = z.string().trim();
const nonnegativeDecimal = z.string().regex(/^\d+(?:\.\d{1,12})?$/, "Enter a nonnegative decimal number");
const positiveDecimal = nonnegativeDecimal.refine((value) => decimalParts(value)?.digits !== 0n, "Must be greater than zero");
const optionalDecimal = z.union([z.literal(""), nonnegativeDecimal]);
const date = z.string().refine((value) => !value || isCalendarDate(value), "Enter a valid date (YYYY-MM-DD)");

export const purchaseOrderFormSchema = z.object({
  external_po_number: identifier,
  vendor_name: optionalText,
  buyer_name: optionalText,
  issue_date: date,
  currency: z.string().regex(/^[A-Z]{3}$/, "Use a three-letter uppercase currency code"),
  subtotal: optionalDecimal,
  tax: optionalDecimal,
  total: optionalDecimal,
  lines: z.array(z.object({
    line_number: identifier,
    description: identifier,
    ordered_quantity: positiveDecimal,
    unit_price: nonnegativeDecimal,
    line_total: optionalDecimal,
  })).min(1, "Add at least one line item"),
  correction_reason: z.string().trim().max(2000, "Keep the reason within 2,000 characters"),
});
export type PurchaseOrderForm = z.infer<typeof purchaseOrderFormSchema>;

export const receiptFormSchema = z.object({
  external_receipt_number: identifier,
  referenced_po_number: identifier,
  received_at: z.string().refine(isUtcDateTimeInput, "Enter a valid UTC date and time"),
  supplier: optionalText,
  lines: z.array(z.object({
    purchase_order_line_number: identifier,
    description: identifier,
    received_quantity: positiveDecimal,
    accepted_quantity: positiveDecimal,
    rejected_quantity: nonnegativeDecimal,
  }).superRefine((line, context) => {
    if (!validDecimal(line.received_quantity) || !validDecimal(line.accepted_quantity) || !validDecimal(line.rejected_quantity)) return;
    if (compareDecimal(addDecimals(line.accepted_quantity, line.rejected_quantity), line.received_quantity) !== 0) {
      context.addIssue({ code: "custom", path: ["accepted_quantity"], message: "Accepted plus rejected must equal received" });
    }
  })).min(1, "Add at least one line item"),
  correction_reason: z.string().trim().max(2000, "Keep the reason within 2,000 characters"),
}).superRefine((values, context) => {
  const seen = new Set<string>();
  values.lines.forEach((line, index) => {
    const number = line.purchase_order_line_number.trim();
    if (number && seen.has(number)) context.addIssue({ code: "custom", path: ["lines", index, "purchase_order_line_number"], message: "PO line numbers must be unique" });
    seen.add(number);
  });
});
export type ReceiptForm = z.infer<typeof receiptFormSchema>;

export function initialPurchaseOrder(extracted: PurchaseOrderExtract): PurchaseOrderForm {
  return {
    external_po_number: extracted.po_number.value ?? "",
    vendor_name: extracted.vendor.value ?? "",
    buyer_name: extracted.buyer.value ?? "",
    issue_date: extracted.issue_date.value ?? "",
    currency: extracted.currency.value ?? "",
    subtotal: extracted.subtotal.value ?? "",
    tax: extracted.tax.value ?? "",
    total: extracted.total.value ?? "",
    lines: extracted.line_items.map((line) => ({
      line_number: line.line_number.value ?? "",
      description: line.description.value ?? "",
      ordered_quantity: line.ordered_quantity.value ?? "",
      unit_price: line.unit_price.value ?? "",
      line_total: line.line_total.value ?? "",
    })),
    correction_reason: "",
  };
}

export function initialReceipt(extracted: ReceiptExtract): ReceiptForm {
  return {
    external_receipt_number: extracted.receipt_number.value ?? "",
    referenced_po_number: extracted.referenced_po_number.value ?? "",
    received_at: extracted.received_date.value ? `${extracted.received_date.value}T00:00` : "",
    supplier: extracted.supplier.value ?? "",
    lines: extracted.line_items.map((line) => ({
      purchase_order_line_number: "",
      description: line.description.value ?? "",
      received_quantity: line.received_quantity.value ?? "",
      accepted_quantity: line.accepted_quantity.value ?? "",
      rejected_quantity: line.rejected_quantity.value ?? "",
    })),
    correction_reason: "",
  };
}

export function purchaseOrderPayload(values: PurchaseOrderForm): ApiSchema<"PurchaseOrderConfirmationValues"> {
  return {
    external_po_number: values.external_po_number.trim(),
    vendor_name: values.vendor_name.trim() || null,
    buyer_name: values.buyer_name.trim() || null,
    issue_date: values.issue_date || null,
    currency: values.currency,
    subtotal: values.subtotal || null,
    tax: values.tax || null,
    total: values.total || null,
    lines: values.lines.map((line) => ({
      line_number: line.line_number.trim(),
      description: line.description.trim(),
      ordered_quantity: line.ordered_quantity,
      unit_price: line.unit_price,
      line_total: line.line_total || null,
    })),
  };
}

export function receiptPayload(values: ReceiptForm): ApiSchema<"ReceiptConfirmationValues"> {
  return {
    external_receipt_number: values.external_receipt_number.trim(),
    referenced_po_number: values.referenced_po_number.trim(),
    received_at: `${values.received_at}:00Z`,
    supplier: values.supplier.trim() || null,
    lines: values.lines.map((line) => ({
      purchase_order_line_number: line.purchase_order_line_number.trim(),
      description: line.description.trim(),
      received_quantity: line.received_quantity,
      accepted_quantity: line.accepted_quantity,
      rejected_quantity: line.rejected_quantity,
    })),
  };
}

export interface ChangeSummary {
  changedFields: number;
  retainedFields: number;
  addedLines: number;
  removedLines: number;
  materiallyChanged: boolean;
}

function summarize(pairs: [string | null, string, boolean?][], oldLines: number, sourceIndices: (number | undefined)[]): ChangeSummary {
  const changedFields = pairs.filter(([oldValue, newValue, decimal]) => decimal ? !sameOptionalDecimal(oldValue, newValue) : (oldValue ?? "") !== newValue).length;
  const retainedLines = new Set(sourceIndices.filter((index): index is number => index !== undefined)).size;
  const addedLines = sourceIndices.length - retainedLines;
  const removedLines = oldLines - retainedLines;
  return {
    changedFields,
    retainedFields: pairs.length - changedFields,
    addedLines,
    removedLines,
    materiallyChanged: changedFields > 0 || addedLines > 0 || removedLines > 0,
  };
}

export function purchaseOrderChanges(extracted: PurchaseOrderExtract, values: PurchaseOrderForm, sourceIndices: (number | undefined)[] = values.lines.map((_, index) => index)): ChangeSummary {
  const pairs: [string | null, string, boolean?][] = [
    [extracted.po_number.value, values.external_po_number], [extracted.vendor.value, values.vendor_name],
    [extracted.buyer.value, values.buyer_name], [extracted.issue_date.value, values.issue_date],
    [extracted.currency.value, values.currency], [extracted.subtotal.value, values.subtotal],
    [extracted.tax.value, values.tax], [extracted.total.value, values.total],
  ];
  values.lines.forEach((line, index) => {
    const source = extracted.line_items[sourceIndices[index] ?? -1];
    if (source) pairs.push([source.line_number.value, line.line_number], [source.description.value, line.description], [source.ordered_quantity.value, line.ordered_quantity], [source.unit_price.value, line.unit_price], [source.line_total.value, line.line_total, true]);
  });
  return summarize(pairs, extracted.line_items.length, sourceIndices);
}

export function receiptChanges(extracted: ReceiptExtract, values: ReceiptForm, sourceIndices: (number | undefined)[] = values.lines.map((_, index) => index)): ChangeSummary {
  const pairs: [string | null, string, boolean?][] = [
    [extracted.receipt_number.value, values.external_receipt_number],
    [extracted.referenced_po_number.value, values.referenced_po_number],
    [extracted.received_date.value, values.received_at.slice(0, 10)],
    [extracted.supplier.value, values.supplier],
  ];
  values.lines.forEach((line, index) => {
    const source = extracted.line_items[sourceIndices[index] ?? -1];
    if (source) pairs.push([source.description.value, line.description], [source.received_quantity.value, line.received_quantity], [source.accepted_quantity.value, line.accepted_quantity], [source.rejected_quantity.value, line.rejected_quantity]);
  });
  return summarize(pairs, extracted.line_items.length, sourceIndices);
}

interface DecimalParts { digits: bigint; scale: number }
function decimalParts(value: string): DecimalParts | null {
  if (!/^\d+(?:\.\d{1,12})?$/.test(value)) return null;
  const [integer, fraction = ""] = value.split(".");
  return { digits: BigInt(integer + fraction), scale: fraction.length };
}
function validDecimal(value: string): boolean { return decimalParts(value) !== null; }
function compareDecimal(left: string, right: string): number | null {
  const a = decimalParts(left); const b = decimalParts(right);
  if (!a || !b) return null;
  const scale = Math.max(a.scale, b.scale);
  const adjustedA = a.digits * 10n ** BigInt(scale - a.scale);
  const adjustedB = b.digits * 10n ** BigInt(scale - b.scale);
  return adjustedA < adjustedB ? -1 : adjustedA > adjustedB ? 1 : 0;
}
export function sameOptionalDecimal(left: string | null, right: string): boolean {
  if (left === null || right === "") return (left ?? "") === right;
  return compareDecimal(left, right) === 0;
}
function addDecimals(left: string, right: string): string {
  const a = decimalParts(left); const b = decimalParts(right);
  if (!a || !b) return "";
  const scale = Math.max(a.scale, b.scale);
  return formatDecimal(a.digits * 10n ** BigInt(scale - a.scale) + b.digits * 10n ** BigInt(scale - b.scale), scale);
}
function formatDecimal(digits: bigint, scale: number): string {
  if (scale === 0) return digits.toString();
  const padded = digits.toString().padStart(scale + 1, "0");
  return `${padded.slice(0, -scale)}.${padded.slice(-scale)}`.replace(/\.?0+$/, "");
}
export function calculatedAmount(quantity: string, unitPrice: string): string | null {
  const a = decimalParts(quantity); const b = decimalParts(unitPrice);
  return a && b ? formatDecimal(a.digits * b.digits, a.scale + b.scale) : null;
}

export function amountMismatch(extractedAmount: string | null, quantity: string, unitPrice: string): boolean {
  const calculated = calculatedAmount(quantity, unitPrice);
  return extractedAmount !== null && calculated !== null && compareDecimal(extractedAmount, calculated) !== 0;
}

function isCalendarDate(value: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]); const month = Number(match[2]); const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() + 1 === month && parsed.getUTCDate() === day;
}
function isUtcDateTimeInput(value: string): boolean {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})$/.exec(value);
  return Boolean(match && isCalendarDate(match[1]) && Number(match[2]) < 24 && Number(match[3]) < 60);
}

export interface BackendIssue { path: string; message: string }
export function backendIssues(detail: unknown): BackendIssue[] {
  if (!Array.isArray(detail)) return [];
  return detail.flatMap((item: unknown) => {
    if (!item || typeof item !== "object" || !("loc" in item) || !("msg" in item) || !Array.isArray(item.loc) || typeof item.msg !== "string") return [];
    const path = item.loc.filter((part: unknown) => typeof part === "string" || typeof part === "number").filter((part: string | number) => part !== "body" && part !== "confirmed").join(".");
    return path ? [{ path, message: item.msg.slice(0, 300) }] : [];
  });
}
