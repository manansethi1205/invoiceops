"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FilePlus2, RefreshCw } from "lucide-react";
import dynamic from "next/dynamic";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { CaseTimeline } from "@/components/case-timeline";
import { ConfirmationEditor } from "@/components/confirmation-editor";
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
  const session = useQuery<{ subject: string; roles: string[] }>({ queryKey: ["auth-session"], queryFn: async () => (await fetch("/api/auth/session")).json() });
  const canOperate = session.data?.roles.some((role) => ["operator", "reviewer", "admin"].includes(role)) ?? false;
  const canReview = session.data?.roles.some((role) => ["reviewer", "admin"].includes(role)) ?? false;
  const payableCase = useQuery({ queryKey: ["case", caseId], queryFn: () => required(api.GET("/v1/cases/{case_id}", { params: { path: { case_id: caseId } } })), refetchInterval: 2000 });
  const documents = useQuery({ queryKey: ["case-documents", caseId], queryFn: () => required(api.GET("/v1/cases/{case_id}/documents", { params: { path: { case_id: caseId } } })), refetchInterval: 2000 });
  const extractions = useQuery({ queryKey: ["case-extractions", caseId], queryFn: () => required(api.GET("/v1/cases/{case_id}/extractions", { params: { path: { case_id: caseId } } })), refetchInterval: 2000 });
  const selectedId = search.get("document") ?? documents.data?.find((item) => item.is_active)?.document_id;
  const selected = documents.data?.find((item) => item.document_id === selectedId) ?? documents.data?.[0];
  const extraction = extractions.data?.find((item) => item.document_id === selected?.document_id);
  const fields = useMemo(() => extractionFields(extraction), [extraction]);
  const [selectedField, setSelectedField] = useState<string>("");
  const [selectedEvidence, setSelectedEvidence] = useState<Evidence[] | null>(null);
  const focusEvidence = (region: Evidence[]) => {
    setSelectedEvidence(region);
  };
  const [matchKey] = useState(() => new LogicalActionIdempotencyKey());
  const evidence = selectedEvidence ?? fields.find((field) => field.key === selectedField)?.evidence ?? fields[0]?.evidence ?? [];
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
    {canOperate ? <CaseAttachmentControls caseId={caseId} payableCase={payableCase.data} documents={documents.data ?? []} selected={selected} onAttached={async (documentId) => { await Promise.all([queryClient.invalidateQueries({ queryKey: ["case", caseId] }), queryClient.invalidateQueries({ queryKey: ["case-documents", caseId] }), queryClient.invalidateQueries({ queryKey: ["case-extractions", caseId] })]); router.replace(`/cases/${caseId}?document=${documentId}`); }}/> : null}
    <div className="case-tabs" role="tablist" aria-label="Case documents">{documents.data?.map((item, index) => <button role="tab" aria-selected={item.document_id === selected?.document_id} className={item.document_id === selected?.document_id ? "active" : ""} key={item.id} onClick={() => { setSelectedEvidence(null); router.replace(`/cases/${caseId}?document=${item.document_id}`); }}>{tabLabel(item, index)}{!item.is_active ? " · superseded" : ""}</button>)}</div>
    {selected ? <div className="workspace-grid"><section><DocumentViewer documentId={selected.document_id} contentType={selected.content_type} evidence={evidence} focusOnEvidence={selectedEvidence !== null}/></section><aside className="stack">
      <section className="card"><div className="card-header"><h2>{selected.filename}</h2><StatusBadge value={extraction?.status ?? selected.job_status}/></div><dl className="document-meta"><div><dt>Role</dt><dd>{selected.role.replaceAll("_", " ")}</dd></div><div><dt>Processing</dt><dd>{selected.job_status}</dd></div><div><dt>Extraction</dt><dd>{extraction?.extractor_name ?? "Pending"}</dd></div><div><dt>Confirmation</dt><dd>{selected.confirmation_status}</dd></div></dl></section>
      <section className="card"><div className="card-header"><h2>Extracted fields</h2><span className="muted">{extraction?.used_ocr ? "OCR used" : "Embedded text"}</span></div>{fields.length ? <div className="field-list">{fields.map((field) => <button className={`extracted-field ${selectedField === field.key ? "selected" : ""}`} key={field.key} aria-pressed={selectedField === field.key} onClick={() => { setSelectedField(field.key); focusEvidence(field.evidence); }}><span><small>{field.label}</small><strong>{field.value ?? "Missing"}</strong></span><span className={`status status-${field.status === "extracted" ? "success" : field.status === "ambiguous" ? "warning" : "neutral"}`}>{field.status}</span><code>{field.ruleId ?? "No rule candidate"}</code></button>)}</div> : <p className="muted">Extraction is still pending.</p>}</section>
      {canReview && extraction && selected.role !== "INVOICE" && selected.confirmation_status !== "CONFIRMED" ? <ConfirmationEditor caseId={caseId} payableCase={payableCase.data} document={selected} extraction={extraction} onSelectEvidence={focusEvidence} onReload={async () => { const results = await Promise.all([payableCase.refetch(), documents.refetch(), extractions.refetch()]); if (results.some((result) => result.isError)) throw new Error("Case reload failed"); }} onConfirmed={async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: ["case", caseId] }), queryClient.invalidateQueries({ queryKey: ["case-documents", caseId] })]); }}/> : null}
      {canOperate ? <section className="card"><div className="card-header"><h2>Deterministic match</h2></div><button className="button button-primary" disabled={payableCase.data.status !== "READY_TO_MATCH" || match.isPending} onClick={() => match.mutate()}>Run case match</button>{match.error ? <p className="field-error">{errorMessage(match.error)}</p> : null}<p className="help-text">Only confirmed canonical purchase orders and receipts are used.</p></section> : null}
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
