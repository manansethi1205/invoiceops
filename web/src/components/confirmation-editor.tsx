"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useFieldArray, useForm, useWatch, type UseFormRegisterReturn } from "react-hook-form";

import { api, ApiError, errorMessage, required, type ApiSchema } from "@/lib/api/client";
import {
  amountMismatch, backendIssues, calculatedAmount, initialPurchaseOrder, initialReceipt,
  purchaseOrderChanges, purchaseOrderFormSchema, purchaseOrderPayload,
  receiptChanges, receiptFormSchema, receiptPayload, sameOptionalDecimal,
  type BackendIssue, type ChangeSummary, type ExtractedCell,
  type PurchaseOrderExtract, type PurchaseOrderForm, type ReceiptExtract, type ReceiptForm,
} from "@/lib/confirmation";
import { LogicalActionIdempotencyKey } from "@/lib/idempotency";

type CaseRead = ApiSchema<"CaseRead">;
type CaseDocument = ApiSchema<"CaseDocumentRead">;
type CaseExtraction = ApiSchema<"CaseExtractionRead">;
type Evidence = ApiSchema<"EvidenceSpan">;

interface EditorProps {
  caseId: string;
  payableCase: CaseRead;
  document: CaseDocument;
  extraction: CaseExtraction;
  onConfirmed: () => Promise<void>;
  onReload: () => Promise<void>;
  onSelectEvidence: (evidence: Evidence[]) => void;
}

function isPurchaseOrder(output: CaseExtraction["output"]): output is PurchaseOrderExtract {
  return output !== null && "po_number" in output;
}
function isReceipt(output: CaseExtraction["output"]): output is ReceiptExtract {
  return output !== null && "receipt_number" in output;
}

export function ConfirmationEditor(props: EditorProps) {
  const { document, extraction } = props;
  if (extraction.status.toUpperCase() !== "SUCCEEDED" || !extraction.output) return null;
  if (document.role === "PURCHASE_ORDER" && isPurchaseOrder(extraction.output)) {
    return <PurchaseOrderEditor key={`${document.id}:${extraction.id}`} {...props} extracted={extraction.output}/>;
  }
  if ((document.role === "GOODS_RECEIPT" || document.role === "DELIVERY_NOTE") && isReceipt(extraction.output)) {
    return <ReceiptEditor key={`${document.id}:${extraction.id}`} {...props} extracted={extraction.output}/>;
  }
  return <section className="card"><p className="field-error">This extraction cannot be confirmed for its document role.</p></section>;
}

function PurchaseOrderEditor({ extracted, ...props }: EditorProps & { extracted: PurchaseOrderExtract }) {
  const { caseId, payableCase, extraction, onConfirmed, onReload, onSelectEvidence } = props;
  const form = useForm<PurchaseOrderForm>({ resolver: zodResolver(purchaseOrderFormSchema), defaultValues: initialPurchaseOrder(extracted), mode: "onSubmit" });
  const lines = useFieldArray({ control: form.control, name: "lines" });
  const [sourceByFieldId] = useState(() => new Map(lines.fields.map((line, index) => [line.id, index])));
  const sourceIndices = lines.fields.map((line) => sourceByFieldId.get(line.id));
  useWatch({ control: form.control });
  const values = form.getValues();
  const summary = purchaseOrderChanges(extracted, values, sourceIndices);
  const [key] = useState(() => new LogicalActionIdempotencyKey());
  const [serverIssues, setServerIssues] = useState<BackendIssue[]>([]);
  const [stale, setStale] = useState(false);
  const [reloading, setReloading] = useState(false);
  const mutation = useMutation({
    mutationFn: async (confirmed: PurchaseOrderForm) => {
      const payload = purchaseOrderPayload(confirmed);
      const request: Omit<ApiSchema<"PurchaseOrderConfirmation">, "idempotency_key"> = {
        expected_case_version: payableCase.version,
        extraction_run_id: extraction.id,
        extractor_version: extraction.extractor_version,
        confirmed: payload,
        correction_reason: confirmed.correction_reason.trim() || null,
      };
      const fingerprint = JSON.stringify({ caseId, documentId: props.document.document_id, ...request });
      return required(api.POST("/v1/cases/{case_id}/purchase-order/confirm", {
        params: { path: { case_id: caseId } },
        body: { ...request, idempotency_key: key.keyFor(fingerprint) },
      }));
    },
    onSuccess: async () => { key.complete(); await onConfirmed(); },
    onError: (error) => handleBackendError(error, setServerIssues, setStale),
  });
  const submit = form.handleSubmit((confirmed) => {
    if (purchaseOrderChanges(extracted, confirmed, sourceIndices).materiallyChanged && !confirmed.correction_reason.trim()) {
      form.setError("correction_reason", { message: "Explain the correction before confirming" });
      form.setFocus("correction_reason");
      return;
    }
    setServerIssues([]);
    mutation.mutate(confirmed);
  });
  const issue = (path: string) => serverIssues.find((item) => item.path === path)?.message;
  const reload = () => reloadLatest(onReload, setReloading, setStale, setServerIssues);
  return <section className="card confirmation-editor" aria-label="Purchase order confirmation">
    <h2>Human confirmation</h2>
    <p className="help-text">Review each value against the source. Confirmation creates a separate canonical record; the extracted record stays unchanged.</p>
    <form noValidate onSubmit={submit} onChangeCapture={() => setServerIssues([])}>
      <div className="confirmation-fields">
        <ConfirmationField name="external_po_number" label="PO number" extracted={extracted.po_number} value={values.external_po_number} registration={form.register("external_po_number")} error={form.formState.errors.external_po_number?.message ?? issue("external_po_number")} onSelectEvidence={onSelectEvidence}/>
        <ConfirmationField name="vendor_name" label="Supplier name" extracted={extracted.vendor} value={values.vendor_name} registration={form.register("vendor_name")} error={form.formState.errors.vendor_name?.message ?? issue("vendor_name")} onSelectEvidence={onSelectEvidence}/>
        <ConfirmationField name="buyer_name" label="Buyer name" extracted={extracted.buyer} value={values.buyer_name} registration={form.register("buyer_name")} error={form.formState.errors.buyer_name?.message ?? issue("buyer_name")} onSelectEvidence={onSelectEvidence}/>
        <ConfirmationField name="issue_date" label="Order date" type="date" extracted={extracted.issue_date} value={values.issue_date} registration={form.register("issue_date")} error={form.formState.errors.issue_date?.message ?? issue("issue_date")} onSelectEvidence={onSelectEvidence}/>
        <ConfirmationField name="currency" label="Currency" extracted={extracted.currency} value={values.currency} registration={form.register("currency")} error={form.formState.errors.currency?.message ?? issue("currency")} onSelectEvidence={onSelectEvidence}/>
        <ConfirmationField name="subtotal" label="Subtotal" inputMode="decimal" extracted={extracted.subtotal} value={values.subtotal} registration={form.register("subtotal")} error={form.formState.errors.subtotal?.message ?? issue("subtotal")} onSelectEvidence={onSelectEvidence}/>
        <ConfirmationField name="tax" label="Tax" inputMode="decimal" extracted={extracted.tax} value={values.tax} registration={form.register("tax")} error={form.formState.errors.tax?.message ?? issue("tax")} onSelectEvidence={onSelectEvidence}/>
        <ConfirmationField name="total" label="Total" inputMode="decimal" extracted={extracted.total} value={values.total} registration={form.register("total")} error={form.formState.errors.total?.message ?? issue("total")} onSelectEvidence={onSelectEvidence}/>
      </div>
      <div className="confirmation-section-heading"><h3>Line items</h3><button className="button button-secondary" type="button" onClick={() => lines.append({ line_number: "", description: "", ordered_quantity: "", unit_price: "", line_total: "" })}>Add line item</button></div>
      {form.formState.errors.lines?.root?.message ? <p className="field-error" role="alert">{form.formState.errors.lines.root.message}</p> : null}
      <div className="confirmation-table-scroll"><table className="confirmation-table"><thead><tr><th scope="col">Line</th><th scope="col">Description</th><th scope="col">Quantity</th><th scope="col">Unit price</th><th scope="col">Amount</th><th scope="col">Action</th></tr></thead><tbody>{lines.fields.map((entry, index) => {
        const source = extracted.line_items[sourceIndices[index] ?? -1];
        const current = values.lines?.[index];
        return <tr key={entry.id}>
          <td><ConfirmationField compact name={`lines.${index}.line_number`} label={`Line ${index + 1} number`} extracted={source?.line_number} value={current?.line_number ?? ""} registration={form.register(`lines.${index}.line_number`)} error={form.formState.errors.lines?.[index]?.line_number?.message ?? issue(`lines.${index}.line_number`)} onSelectEvidence={onSelectEvidence}/></td>
          <td><ConfirmationField compact name={`lines.${index}.description`} label={`Line ${index + 1} description`} extracted={source?.description} value={current?.description ?? ""} registration={form.register(`lines.${index}.description`)} error={form.formState.errors.lines?.[index]?.description?.message ?? issue(`lines.${index}.description`)} onSelectEvidence={onSelectEvidence}/></td>
          <td><ConfirmationField compact name={`lines.${index}.ordered_quantity`} label={`Line ${index + 1} quantity`} inputMode="decimal" extracted={source?.ordered_quantity} value={current?.ordered_quantity ?? ""} registration={form.register(`lines.${index}.ordered_quantity`)} error={form.formState.errors.lines?.[index]?.ordered_quantity?.message ?? issue(`lines.${index}.ordered_quantity`)} onSelectEvidence={onSelectEvidence}/></td>
          <td><ConfirmationField compact name={`lines.${index}.unit_price`} label={`Line ${index + 1} unit price`} inputMode="decimal" extracted={source?.unit_price} value={current?.unit_price ?? ""} registration={form.register(`lines.${index}.unit_price`)} error={form.formState.errors.lines?.[index]?.unit_price?.message ?? issue(`lines.${index}.unit_price`)} onSelectEvidence={onSelectEvidence}/></td>
          <td><ConfirmationField compact name={`lines.${index}.line_total`} label={`Line ${index + 1} amount`} inputMode="decimal" extracted={source?.line_total} value={current?.line_total ?? ""} decimalEquality registration={form.register(`lines.${index}.line_total`)} error={form.formState.errors.lines?.[index]?.line_total?.message ?? issue(`lines.${index}.line_total`)} onSelectEvidence={onSelectEvidence}/><span className="confirmation-amount-label">Quantity × unit price</span><strong className="confirmation-amount">{current ? calculatedAmount(current.ordered_quantity, current.unit_price) ?? "—" : "—"}</strong>{current?.line_total && amountMismatch(current.line_total, current.ordered_quantity, current.unit_price) ? <span className="field-error" role="alert">Confirmed amount differs from calculated amount; matching will apply policy tolerance</span> : null}</td>
          <td><button className="button button-secondary" type="button" aria-label={`Remove line ${index + 1}`} onClick={() => lines.remove(index)}>Remove</button></td>
        </tr>;
      })}</tbody></table></div>
      <ConfirmationFooter summary={summary} reasonRegistration={form.register("correction_reason")} reasonError={form.formState.errors.correction_reason?.message ?? issue("correction_reason")} reloadError={issue("reload")} pending={mutation.isPending} stale={stale} reloading={reloading} error={mutation.error} onReload={reload}/>
    </form>
  </section>;
}

function ReceiptEditor({ extracted, ...props }: EditorProps & { extracted: ReceiptExtract }) {
  const { caseId, payableCase, extraction, document, onConfirmed, onReload, onSelectEvidence } = props;
  const form = useForm<ReceiptForm>({ resolver: zodResolver(receiptFormSchema), defaultValues: initialReceipt(extracted), mode: "onSubmit" });
  const lines = useFieldArray({ control: form.control, name: "lines" });
  const [sourceByFieldId] = useState(() => new Map(lines.fields.map((line, index) => [line.id, index])));
  const sourceIndices = lines.fields.map((line) => sourceByFieldId.get(line.id));
  useWatch({ control: form.control });
  const values = form.getValues();
  const summary = receiptChanges(extracted, values, sourceIndices);
  const [key] = useState(() => new LogicalActionIdempotencyKey());
  const [serverIssues, setServerIssues] = useState<BackendIssue[]>([]);
  const [stale, setStale] = useState(false);
  const [reloading, setReloading] = useState(false);
  const mutation = useMutation({
    mutationFn: async (confirmed: ReceiptForm) => {
      const request: Omit<ApiSchema<"ReceiptConfirmation">, "idempotency_key"> = {
        expected_case_version: payableCase.version,
        extraction_run_id: extraction.id,
        extractor_version: extraction.extractor_version,
        confirmed: receiptPayload(confirmed),
        correction_reason: confirmed.correction_reason.trim() || null,
      };
      const fingerprint = JSON.stringify({ caseId, documentId: document.document_id, ...request });
      return required(api.POST("/v1/cases/{case_id}/receipts/{document_id}/confirm", {
        params: { path: { case_id: caseId, document_id: document.document_id } },
        body: { ...request, idempotency_key: key.keyFor(fingerprint) },
      }));
    },
    onSuccess: async () => { key.complete(); await onConfirmed(); },
    onError: (error) => handleBackendError(error, setServerIssues, setStale),
  });
  const submit = form.handleSubmit((confirmed) => {
    if (receiptChanges(extracted, confirmed, sourceIndices).materiallyChanged && !confirmed.correction_reason.trim()) {
      form.setError("correction_reason", { message: "Explain the correction before confirming" });
      form.setFocus("correction_reason");
      return;
    }
    setServerIssues([]);
    mutation.mutate(confirmed);
  });
  const issue = (path: string) => serverIssues.find((item) => item.path === path)?.message;
  const reload = () => reloadLatest(onReload, setReloading, setStale, setServerIssues);
  return <section className="card confirmation-editor" aria-label="Receipt confirmation">
    <h2>Human confirmation</h2>
    <p className="help-text">Link each receipt line to a confirmed PO line. The extracted document remains unchanged.</p>
    <form noValidate onSubmit={submit} onChangeCapture={() => setServerIssues([])}>
      <div className="confirmation-fields">
        <ConfirmationField name="external_receipt_number" label="Receipt number" extracted={extracted.receipt_number} value={values.external_receipt_number} registration={form.register("external_receipt_number")} error={form.formState.errors.external_receipt_number?.message ?? issue("external_receipt_number")} onSelectEvidence={onSelectEvidence}/>
        <ConfirmationField name="referenced_po_number" label="PO reference" extracted={extracted.referenced_po_number} value={values.referenced_po_number} registration={form.register("referenced_po_number")} error={form.formState.errors.referenced_po_number?.message ?? issue("referenced_po_number")} onSelectEvidence={onSelectEvidence}/>
        <ConfirmationField name="received_at" label="Receipt date and time (UTC)" type="datetime-local" extracted={extracted.received_date} compareValue={values.received_at.slice(0, 10)} value={values.received_at} registration={form.register("received_at")} error={form.formState.errors.received_at?.message ?? issue("received_at")} onSelectEvidence={onSelectEvidence}/>
        <ConfirmationField name="supplier" label="Supplier" extracted={extracted.supplier} value={values.supplier} registration={form.register("supplier")} error={form.formState.errors.supplier?.message ?? issue("supplier")} onSelectEvidence={onSelectEvidence}/>
      </div>
      <div className="confirmation-section-heading"><h3>Received lines</h3><button className="button button-secondary" type="button" onClick={() => lines.append({ purchase_order_line_number: "", description: "", received_quantity: "", accepted_quantity: "", rejected_quantity: "0" })}>Add line item</button></div>
      {form.formState.errors.lines?.root?.message ? <p className="field-error" role="alert">{form.formState.errors.lines.root.message}</p> : null}
      <div className="confirmation-table-scroll"><table className="confirmation-table"><thead><tr><th scope="col">PO line</th><th scope="col">Description</th><th scope="col">Received</th><th scope="col">Accepted</th><th scope="col">Rejected</th><th scope="col">Action</th></tr></thead><tbody>{lines.fields.map((entry, index) => {
        const source = extracted.line_items[sourceIndices[index] ?? -1];
        const current = values.lines?.[index];
        return <tr key={entry.id}>
          <td><ConfirmationField compact name={`lines.${index}.purchase_order_line_number`} label={`Line ${index + 1} PO reference`} value={current?.purchase_order_line_number ?? ""} registration={form.register(`lines.${index}.purchase_order_line_number`)} error={form.formState.errors.lines?.[index]?.purchase_order_line_number?.message ?? issue(`lines.${index}.purchase_order_line_number`)} onSelectEvidence={onSelectEvidence}/></td>
          <td><ConfirmationField compact name={`lines.${index}.description`} label={`Line ${index + 1} description`} extracted={source?.description} value={current?.description ?? ""} registration={form.register(`lines.${index}.description`)} error={form.formState.errors.lines?.[index]?.description?.message ?? issue(`lines.${index}.description`)} onSelectEvidence={onSelectEvidence}/></td>
          <td><ConfirmationField compact name={`lines.${index}.received_quantity`} label={`Line ${index + 1} received`} inputMode="decimal" extracted={source?.received_quantity} value={current?.received_quantity ?? ""} registration={form.register(`lines.${index}.received_quantity`)} error={form.formState.errors.lines?.[index]?.received_quantity?.message ?? issue(`lines.${index}.received_quantity`)} onSelectEvidence={onSelectEvidence}/></td>
          <td><ConfirmationField compact name={`lines.${index}.accepted_quantity`} label={`Line ${index + 1} accepted`} inputMode="decimal" extracted={source?.accepted_quantity} value={current?.accepted_quantity ?? ""} registration={form.register(`lines.${index}.accepted_quantity`)} error={form.formState.errors.lines?.[index]?.accepted_quantity?.message ?? issue(`lines.${index}.accepted_quantity`)} onSelectEvidence={onSelectEvidence}/></td>
          <td><ConfirmationField compact name={`lines.${index}.rejected_quantity`} label={`Line ${index + 1} rejected`} inputMode="decimal" extracted={source?.rejected_quantity} value={current?.rejected_quantity ?? ""} registration={form.register(`lines.${index}.rejected_quantity`)} error={form.formState.errors.lines?.[index]?.rejected_quantity?.message ?? issue(`lines.${index}.rejected_quantity`)} onSelectEvidence={onSelectEvidence}/></td>
          <td><button className="button button-secondary" type="button" aria-label={`Remove line ${index + 1}`} onClick={() => lines.remove(index)}>Remove</button></td>
        </tr>;
      })}</tbody></table></div>
      <ConfirmationFooter summary={summary} reasonRegistration={form.register("correction_reason")} reasonError={form.formState.errors.correction_reason?.message ?? issue("correction_reason")} reloadError={issue("reload")} pending={mutation.isPending} stale={stale} reloading={reloading} error={mutation.error} onReload={reload}/>
    </form>
  </section>;
}

function ConfirmationField({ name, label, extracted, value, compareValue, decimalEquality = false, registration, error, onSelectEvidence, type = "text", inputMode, compact = false }: {
  name: string; label: string; extracted?: ExtractedCell; value: string; compareValue?: string;
  decimalEquality?: boolean;
  registration: UseFormRegisterReturn; error?: string; onSelectEvidence: (evidence: Evidence[]) => void;
  type?: string; inputMode?: React.HTMLAttributes<HTMLInputElement>["inputMode"]; compact?: boolean;
}) {
  const original = extracted?.value ?? "";
  const unchanged = decimalEquality ? sameOptionalDecimal(extracted?.value ?? null, value) : original === (compareValue ?? value);
  const state = error ? "invalid" : !value ? "missing" : unchanged ? "unchanged" : "changed";
  const id = `confirmed-${name.replaceAll(".", "-")}`;
  const errorId = `${id}-error`;
  return <div className={`confirmation-field confirmation-${state} ${compact ? "confirmation-compact" : ""}`}>
    <label htmlFor={id}>{label}</label>
    <span className="confirmation-source">Extracted <strong>{extracted?.value ?? "Missing"}</strong></span>
    <div className="confirmation-confirmed"><span>Confirmed</span><input id={id} type={type} inputMode={inputMode} aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined} {...registration}/></div>
    <span className={`confirmation-state state-${state}`}>{state}</span>
    {extracted?.evidence[0] ? <EvidenceButton label={label} evidence={extracted.evidence} onSelect={onSelectEvidence}/> : <small className="muted">No source region</small>}
    {error ? <span id={errorId} className="field-error" role="alert">{error}</span> : null}
  </div>;
}

function EvidenceButton({ label, evidence, onSelect }: { label: string; evidence: Evidence[]; onSelect: (evidence: Evidence[]) => void }) {
  const first = evidence[0];
  return <button type="button" className="confirmation-evidence" aria-label={`View evidence for ${label}`} onClick={() => onSelect(evidence)}>Page {first.page + 1} · {first.text}</button>;
}

function ConfirmationFooter({ summary, reasonRegistration, reasonError, reloadError, pending, stale, reloading, error, onReload }: {
  summary: ChangeSummary; reasonRegistration: UseFormRegisterReturn; reasonError?: string; reloadError?: string;
  pending: boolean; stale: boolean; reloading: boolean; error: unknown; onReload: () => Promise<void>;
}) {
  return <>
    <div className="confirmation-summary" aria-label="Confirmation summary">
      <strong>Before confirmation</strong>
      <span>{summary.changedFields} fields changed</span><span>{summary.addedLines} line items added</span>
      <span>{summary.removedLines} line items removed</span><span>{summary.retainedFields} extracted values retained</span>
    </div>
    <div className="field"><label htmlFor="correction-reason">Correction reason {summary.materiallyChanged ? "(required)" : "(optional)"}</label><textarea id="correction-reason" rows={3} maxLength={2000} aria-invalid={Boolean(reasonError)} aria-describedby={reasonError ? "correction-reason-error" : undefined} {...reasonRegistration}/>{reasonError ? <span id="correction-reason-error" className="field-error" role="alert">{reasonError}</span> : null}</div>
    {stale ? <div className="notice" role="alert"><strong>The case changed during confirmation.</strong> Reload its latest version before submitting again. Your edits stay visible.{reloadError ? <span className="field-error">{reloadError}</span> : null}<button type="button" className="button button-secondary" disabled={reloading} onClick={() => { void onReload(); }}>{reloading ? "Reloading…" : "Reload latest case"}</button></div> : null}
    {error && !stale && !reasonError ? <p className="field-error" role="alert">{errorMessage(error)}</p> : null}
    <div className="form-actions"><button className="button button-primary" type="submit" disabled={pending || stale}>Confirm canonical record</button></div>
  </>;
}

function handleBackendError(error: unknown, setIssues: (issues: BackendIssue[]) => void, setStale: (value: boolean) => void) {
  if (!(error instanceof ApiError)) return;
  if (error.status === 422) setIssues(backendIssues(error.details));
  if (error.status === 409) {
    if (typeof error.details === "object" && error.details !== null && "code" in error.details && error.details.code === "CORRECTION_REASON_REQUIRED") {
      setIssues([{ path: "correction_reason", message: "Explain the correction before confirming" }]);
    } else setStale(true);
  }
}

async function reloadLatest(onReload: () => Promise<void>, setReloading: (value: boolean) => void, setStale: (value: boolean) => void, setIssues: (issues: BackendIssue[]) => void) {
  setReloading(true);
  try {
    await onReload();
    setIssues([]);
    setStale(false);
  } catch {
    setIssues([{ path: "reload", message: "The latest case could not be loaded. Try again." }]);
  } finally {
    setReloading(false);
  }
}
