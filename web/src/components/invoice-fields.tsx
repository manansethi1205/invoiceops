"use client";

import type { ApiSchema } from "@/lib/api/client";

type Invoice = ApiSchema<"Invoice">;
export type FieldSelection = { key: string; label: string; value: string | null; status: string; ruleId: string | null; evidence: ApiSchema<"EvidenceSpan">[] };

export function invoiceFields(invoice: Invoice): FieldSelection[] {
  const fields = [
    ["invoice_number","Invoice number",invoice.invoice_number], ["invoice_date","Invoice date",invoice.invoice_date], ["currency","Currency",invoice.currency], ["subtotal","Subtotal",invoice.subtotal], ["tax","Tax",invoice.tax], ["total","Total",invoice.total],
  ] as const;
  return fields.map(([key,label,field]) => ({ key, label, value: field.value, status: field.status, ruleId: field.rule_id ?? null, evidence: field.evidence }));
}

export function InvoiceFields({ fields, selected, onSelect }: { fields: FieldSelection[]; selected: string; onSelect: (key: string) => void }) {
  return <div className="field-list">{fields.map((field) => {
    const evidence = field.evidence[0];
    return <button key={field.key} className={`extracted-field ${selected===field.key ? "selected" : ""}`} onClick={() => onSelect(field.key)} aria-pressed={selected===field.key}><span><small>{field.label}</small><strong>{field.value ?? "Missing"}</strong></span><span className={`status status-${field.status === "extracted" ? "success" : field.status === "ambiguous" ? "warning" : "neutral"}`}>{field.status}</span><code>{field.ruleId ?? "No rule candidate"}</code>{evidence ? <span className="field-provenance">{evidence.source} · page {evidence.page + 1} · source “{evidence.text}”</span> : <span className="field-provenance">No source evidence</span>}</button>;
  })}</div>;
}
