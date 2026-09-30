"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FilePlus2, RefreshCw } from "lucide-react";
import dynamic from "next/dynamic";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { CaseTimeline } from "@/components/case-timeline";
import { ErrorState, LoadingState } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import {
  api,
  attachCaseDocument,
  errorMessage,
  required,
  type ApiSchema,
} from "@/lib/api/client";
import { LogicalActionIdempotencyKey } from "@/lib/idempotency";

const DocumentViewer = dynamic(
  () => import("@/components/document-viewer").then((module) => module.DocumentViewer),
  { ssr: false, loading: () => <LoadingState label="Loading document viewer"/> },
);

type CaseDocument = ApiSchema<"CaseDocumentRead">;
type CaseExtraction = ApiSchema<"CaseExtractionRead">;
type Evidence = ApiSchema<"EvidenceSpan">;

export default function PayableCasePage() {
  const { caseId } = useParams<{ caseId: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const payableCase = useQuery({ queryKey: ["case", caseId], queryFn: () => required(api.GET("/v1/cases/{case_id}", { params: { path: { case_id: caseId } } })), refetchInterval: 2000 });
  const documents = useQuery({ queryKey: ["case-documents", caseId], queryFn: () => required(api.GET("/v1/cases/{case_id}/documents", { params: { path: { case_id: caseId } } })), refetchInterval: 2000 });
  const extractions = useQuery({ queryKey: ["case-extractions", caseId], queryFn: () => required(api.GET("/v1/cases/{case_id}/extractions", { params: { path: { case_id: caseId } } })), refetchInterval: 2000 });
  const selectedId = search.get("document") ?? documents.data?.find((item) => item.is_active)?.document_id;
  const selected = documents.data?.find((item) => item.document_id === selectedId) ?? documents.data?.[0];
  const extraction = extractions.data?.find((item) => item.document_id === selected?.document_id);
  const fields = useMemo(() => extractionFields(extraction), [extraction]);
  const [selectedField, setSelectedField] = useState<string>("");
  const [matchKey] = useState(() => new LogicalActionIdempotencyKey());
  const evidence = fields.find((field) => field.key === selectedField)?.evidence ?? fields[0]?.evidence ?? [];
  const match = useMutation({
    mutationFn: () => {
      const expectedVersion = payableCase.data!.version;
      const request = { expected_case_version: expectedVersion };
      const fingerprint = JSON.stringify({ caseId, ...request });
      return required(api.POST("/v1/cases/{case_id}/match", { params: { path: { case_id: caseId } }, body: { ...request, idempotency_key: matchKey.keyFor(fingerprint) } }));
    },
    onSuccess: async () => { matchKey.complete(); await queryClient.invalidateQueries({ queryKey: ["case", caseId] }); },
  });
  if (payableCase.isLoading || documents.isLoading || extractions.isLoading) return <LoadingState label="Loading payable case"/>;
  const queryError = payableCase.error ?? documents.error ?? extractions.error;
  if (queryError) return <ErrorState message={errorMessage(queryError)} retry={() => { void payableCase.refetch(); void documents.refetch(); void extractions.refetch(); }}/>;
  if (!payableCase.data) return null;
  return <><PageHeader eyebrow="Payable case" title={payableCase.data.case_number} description="Evidence remains linked to immutable extraction output. Confirmed business records feed deterministic matching; no result authorizes payment." action={<StatusBadge value={payableCase.data.status}/>}/>
    <CaseAttachmentControls caseId={caseId} payableCase={payableCase.data} documents={documents.data ?? []} selected={selected} onAttached={async (documentId) => { await Promise.all([queryClient.invalidateQueries({ queryKey: ["case", caseId] }), queryClient.invalidateQueries({ queryKey: ["case-documents", caseId] }), queryClient.invalidateQueries({ queryKey: ["case-extractions", caseId] })]); router.replace(`/cases/${caseId}?document=${documentId}`); }}/>
    <div className="case-tabs" role="tablist" aria-label="Case documents">{documents.data?.map((item, index) => <button role="tab" aria-selected={item.document_id === selected?.document_id} className={item.document_id === selected?.document_id ? "active" : ""} key={item.id} onClick={() => router.replace(`/cases/${caseId}?document=${item.document_id}`)}>{tabLabel(item, index)}{!item.is_active ? " · superseded" : ""}</button>)}</div>
    {selected ? <div className="workspace-grid"><section><DocumentViewer documentId={selected.document_id} contentType={selected.content_type} evidence={evidence}/></section><aside className="stack">
      <section className="card"><div className="card-header"><h2>{selected.filename}</h2><StatusBadge value={extraction?.status ?? selected.job_status}/></div><dl className="document-meta"><div><dt>Role</dt><dd>{selected.role.replaceAll("_", " ")}</dd></div><div><dt>Processing</dt><dd>{selected.job_status}</dd></div><div><dt>Extraction</dt><dd>{extraction?.extractor_name ?? "Pending"}</dd></div><div><dt>Confirmation</dt><dd>{selected.confirmation_status}</dd></div></dl></section>
      <section className="card"><div className="card-header"><h2>Extracted fields</h2><span className="muted">{extraction?.used_ocr ? "OCR used" : "Embedded text"}</span></div>{fields.length ? <div className="field-list">{fields.map((field) => <button className={`extracted-field ${selectedField === field.key ? "selected" : ""}`} key={field.key} aria-pressed={selectedField === field.key} onClick={() => setSelectedField(field.key)}><span><small>{field.label}</small><strong>{field.value ?? "Missing"}</strong></span><span className={`status status-${field.status === "extracted" ? "success" : field.status === "ambiguous" ? "warning" : "neutral"}`}>{field.status}</span><code>{field.ruleId ?? "No rule candidate"}</code></button>)}</div> : <p className="muted">Extraction is still pending.</p>}</section>
      {extraction && selected.role !== "INVOICE" && selected.confirmation_status !== "CONFIRMED" ? <ConfirmationEditor caseId={caseId} payableCase={payableCase.data} document={selected} extraction={extraction} onConfirmed={async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: ["case", caseId] }), queryClient.invalidateQueries({ queryKey: ["case-documents", caseId] })]); }}/> : null}
      <section className="card"><div className="card-header"><h2>Deterministic match</h2></div><button className="button button-primary" disabled={payableCase.data.status !== "READY_TO_MATCH" || match.isPending} onClick={() => match.mutate()}>Run case match</button>{match.error ? <p className="field-error">{errorMessage(match.error)}</p> : null}<p className="help-text">Only confirmed canonical purchase orders and receipts are used.</p></section>
      <section className="card"><div className="card-header"><h2>Case timeline</h2></div><CaseTimeline caseId={caseId}/></section>
    </aside></div> : <div className="empty-state"><p>No documents are attached.</p></div>}
  </>;
}

interface PendingAttachment {
  file: File;
  role: CaseDocument["role"];
  idempotencyKey: string;
  supersedesId?: string;
}

function CaseAttachmentControls({ caseId, payableCase, documents, selected, onAttached }: { caseId: string; payableCase: ApiSchema<"CaseRead">; documents: CaseDocument[]; selected?: CaseDocument; onAttached: (documentId: string) => Promise<void> }) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<PendingAttachment | null>(null);
  const mutation = useMutation({
    mutationFn: (attachment: PendingAttachment) => attachCaseDocument(caseId, {
      file: attachment.file,
      role: attachment.role,
      idempotencyKey: attachment.idempotencyKey,
      expectedCaseVersion: payableCase.version,
      supersedesId: attachment.supersedesId,
    }),
    onSuccess: async (result) => {
      setPending(null);
      await onAttached(result.attachment.document_id);
    },
    onError: async () => {
      await queryClient.invalidateQueries({ queryKey: ["case", caseId] });
    },
  });
  const activePo = documents.some((item) => item.role === "PURCHASE_ORDER" && item.is_active);
  const choose = (role: CaseDocument["role"], supersedesId?: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const attachment = { file, role, supersedesId, idempotencyKey: crypto.randomUUID() };
    setPending(attachment);
    mutation.mutate(attachment);
  };
  return <section className="card inline" aria-label="Case attachment actions">
    {!activePo ? <AttachmentInput id="case-add-po" label="Add purchase order" onChange={choose("PURCHASE_ORDER")}/> : null}
    <AttachmentInput id="case-add-receipt" label="Add goods receipt" onChange={choose("GOODS_RECEIPT")}/>
    <AttachmentInput id="case-add-delivery" label="Add delivery note" onChange={choose("DELIVERY_NOTE")}/>
    {selected?.is_active ? <AttachmentInput id="case-replace-document" label={`Replace ${tabLabel(selected, 0).toLowerCase()}`} replace onChange={choose(selected.role, selected.id)}/> : null}
    {pending && mutation.isError ? <button className="button button-secondary" onClick={() => mutation.mutate(pending)}><RefreshCw aria-hidden="true"/>Retry {pending.file.name}</button> : null}
    {mutation.isPending ? <span className="muted" role="status">Uploading evidence…</span> : null}
    {mutation.error ? <span className="field-error" role="alert">{errorMessage(mutation.error)}</span> : null}
  </section>;
}

function AttachmentInput({ id, label, replace = false, onChange }: { id: string; label: string; replace?: boolean; onChange: (event: React.ChangeEvent<HTMLInputElement>) => void }) {
  return <><label className="button button-secondary" htmlFor={id}>{replace ? <RefreshCw aria-hidden="true"/> : <FilePlus2 aria-hidden="true"/>}{label}</label><input className="visually-hidden" id={id} type="file" accept="application/pdf,image/png,image/jpeg" onChange={onChange}/></>;
}

function tabLabel(document: CaseDocument, index: number) {
  if (document.role === "INVOICE") return "Invoice";
  if (document.role === "PURCHASE_ORDER") return "Purchase order";
  return `${document.role === "DELIVERY_NOTE" ? "Delivery note" : "Receipt"} ${index + 1}`;
}

function extractionFields(extraction?: CaseExtraction) {
  if (!extraction?.output) return [];
  const output = extraction.output;
  const names = extraction.role === "INVOICE" ? ["invoice_number", "invoice_date", "currency", "subtotal", "tax", "total"] : extraction.role === "PURCHASE_ORDER" ? ["po_number", "issue_date", "vendor", "buyer", "currency", "subtotal", "tax", "total"] : ["receipt_number", "referenced_po_number", "received_date", "supplier"];
  return names.flatMap((name) => {
    const field = (output as unknown as Record<string, unknown>)[name];
    if (!field || typeof field !== "object" || !("status" in field)) return [];
    const typed = field as { value: unknown; status: string; rule_id?: string | null; evidence: Evidence[] };
    return [{ key: name, label: name.replaceAll("_", " "), value: typed.value === null ? null : String(typed.value), status: typed.status, ruleId: typed.rule_id ?? null, evidence: typed.evidence }];
  });
}

function ConfirmationEditor({ caseId, payableCase, document, extraction, onConfirmed }: { caseId: string; payableCase: ApiSchema<"CaseRead">; document: CaseDocument; extraction: CaseExtraction; onConfirmed: () => Promise<void> }) {
  const [values, setValues] = useState(() => JSON.stringify(initialConfirmation(document.role, extraction.output), null, 2));
  const [reason, setReason] = useState("");
  const [confirmationKey] = useState(() => new LogicalActionIdempotencyKey());
  const mutation = useMutation({ mutationFn: async () => {
    const confirmed = JSON.parse(values) as never;
    const request = { expected_case_version: payableCase.version, extraction_run_id: extraction.id, extractor_version: extraction.extractor_version, confirmed, correction_reason: reason || null };
    const fingerprint = JSON.stringify({ caseId, documentId: document.document_id, ...request });
    const common = { ...request, idempotency_key: confirmationKey.keyFor(fingerprint) };
    if (document.role === "PURCHASE_ORDER") return required(api.POST("/v1/cases/{case_id}/purchase-order/confirm", { params: { path: { case_id: caseId } }, body: common }));
    return required(api.POST("/v1/cases/{case_id}/receipts/{document_id}/confirm", { params: { path: { case_id: caseId, document_id: document.document_id } }, body: common }));
  }, onSuccess: async () => { confirmationKey.complete(); await onConfirmed(); } });
  return <section className="card stack"><div className="card-header"><h2>Human confirmation</h2><StatusBadge value="REQUIRED"/></div><p className="help-text">Compare the document and extracted evidence, then edit the typed values below. The original extraction is never changed.</p><div className="field"><label htmlFor="confirmed-values">Confirmed values</label><textarea id="confirmed-values" rows={14} value={values} onChange={(event) => setValues(event.target.value)} spellCheck={false}/></div><div className="field"><label htmlFor="correction-reason">Correction reason</label><textarea id="correction-reason" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Required when any extracted value changes"/></div>{mutation.error ? <p className="field-error">{errorMessage(mutation.error)}</p> : null}<div className="form-actions"><button className="button button-primary" disabled={mutation.isPending} onClick={() => mutation.mutate()}>Confirm canonical record</button></div></section>;
}

function initialConfirmation(role: CaseDocument["role"], output: CaseExtraction["output"]) {
  if (!output) return {};
  const value = (name: string) => ((output as unknown as Record<string, { value?: unknown }>)[name]?.value ?? null);
  const lines = (output as unknown as { line_items?: Record<string, { value?: unknown }>[] }).line_items ?? [];
  if (role === "PURCHASE_ORDER") return { external_po_number: value("po_number") ?? "", vendor_name: value("vendor"), buyer_name: value("buyer"), currency: value("currency") ?? "", issue_date: value("issue_date"), subtotal: value("subtotal"), tax: value("tax"), total: value("total"), lines: lines.map((line, index) => ({ line_number: line.line_number?.value ?? String(index + 1), description: line.description?.value ?? "", ordered_quantity: line.ordered_quantity?.value ?? "", unit_price: line.unit_price?.value ?? "" })) };
  return { external_receipt_number: value("receipt_number") ?? "", referenced_po_number: value("referenced_po_number") ?? "", supplier: value("supplier"), received_at: value("received_date") ? `${value("received_date")}T00:00:00Z` : "", lines: lines.map((line, index) => ({ purchase_order_line_number: String(index + 1), description: line.description?.value ?? "", received_quantity: line.received_quantity?.value ?? "", accepted_quantity: line.accepted_quantity?.value ?? line.received_quantity?.value ?? "", rejected_quantity: line.rejected_quantity?.value ?? "0" })) };
}
