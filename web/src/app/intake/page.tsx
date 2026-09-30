"use client";

import { useMutation } from "@tanstack/react-query";
import { FileCheck2, FilePlus2, FileUp, RotateCcw, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { z } from "zod";

import { PageHeader } from "@/components/page-header";
import {
  attachCaseDocument,
  createPayableCase,
  errorMessage,
  type ApiSchema,
} from "@/lib/api/client";

const acceptedTypes = ["application/pdf", "image/png", "image/jpeg"];
export const intakeSchema = z.object({
  invoice: z.instanceof(File).refine((file) => acceptedTypes.includes(file.type)),
});
type Role = ApiSchema<"DocumentRole">;
type UploadState = "ready" | "uploading" | "accepted" | "failed";
interface PendingDocument {
  id: string;
  key: string;
  role: Role;
  file: File;
  state: UploadState;
  progress: number;
  error?: string;
}

export default function IntakePage() {
  const router = useRouter();
  const [documents, setDocuments] = useState<PendingDocument[]>([]);
  const [caseKey] = useState(() => crypto.randomUUID());
  const [createdCase, setCreatedCase] = useState<ApiSchema<"CaseRead"> | null>(null);
  const invoice = documents.find((item) => item.role === "INVOICE");
  const purchaseOrder = documents.find((item) => item.role === "PURCHASE_ORDER");
  const receipts = documents.filter(
    (item) => item.role === "GOODS_RECEIPT" || item.role === "DELIVERY_NOTE",
  );
  const invalid = documents.find((item) => !acceptedTypes.includes(item.file.type));
  const mutation = useMutation({
    mutationFn: async () => {
      let payableCase = createdCase ?? (await createPayableCase(caseKey));
      setCreatedCase(payableCase);
      for (const item of documents) {
        setDocumentState(item.id, { state: "uploading", progress: 20, error: undefined });
        try {
          const accepted = await attachCaseDocument(payableCase.id, {
            file: item.file,
            role: item.role,
            idempotencyKey: item.key,
            expectedCaseVersion: payableCase.version,
          });
          payableCase = accepted.case;
          setCreatedCase(payableCase);
          setDocumentState(item.id, { state: "accepted", progress: 100 });
        } catch (error) {
          setDocumentState(item.id, {
            state: "failed",
            progress: 0,
            error: errorMessage(error),
          });
          router.push(`/cases/${payableCase.id}`);
          throw error;
        }
      }
      return payableCase;
    },
    onSuccess: (payableCase) => router.push(`/cases/${payableCase.id}`),
  });

  function setDocumentState(id: string, update: Partial<PendingDocument>) {
    setDocuments((current) =>
      current.map((item) => (item.id === id ? { ...item, ...update } : item)),
    );
  }

  function choose(role: Role, files: FileList | null) {
    if (!files?.length) return;
    setDocuments((current) => {
      let next = [...current];
      for (const file of Array.from(files)) {
        const item: PendingDocument = {
          id: crypto.randomUUID(),
          key: crypto.randomUUID(),
          role,
          file,
          state: "ready",
          progress: 0,
        };
        next =
          role === "INVOICE" || role === "PURCHASE_ORDER"
            ? [...next.filter((entry) => entry.role !== role), item]
            : [...next, item];
      }
      return next;
    });
  }

  const readiness = useMemo(
    () => ({
      invoice: invoice?.state ?? "required",
      purchaseOrder: purchaseOrder?.state ?? "optional",
      receipts: receipts.length ? `${receipts.length} attached` : "optional",
    }),
    [invoice, purchaseOrder, receipts.length],
  );

  return (
    <>
      <PageHeader
        eyebrow="Evidence-backed intake"
        title="New payable case"
        description="Upload the actual invoice, purchase order and receipt or delivery evidence. Supporting extracts require human confirmation before they become canonical business records."
      />
      <div className="two-column">
        <section className="card stack" aria-label="Payable case documents">
          <UploadPanel id="invoice-file" title="Invoice" hint="Required · one active document" role="INVOICE" onFiles={choose}/>
          <UploadPanel id="po-file" title="Purchase order" hint="Optional · requires confirmation" role="PURCHASE_ORDER" onFiles={choose}/>
          <UploadPanel id="receipt-file" title="Goods receipts" hint="Optional · multiple files allowed" role="GOODS_RECEIPT" multiple onFiles={choose}/>
          <UploadPanel id="delivery-file" title="Delivery notes" hint="Optional · multiple files allowed" role="DELIVERY_NOTE" multiple onFiles={choose}/>
          {documents.length ? (
            <div className="stack" aria-live="polite">
              {documents.map((item) => (
                <FileCard key={item.id} item={item} remove={() => setDocuments((current) => current.filter((entry) => entry.id !== item.id))} retry={() => mutation.mutate()}/>
              ))}
            </div>
          ) : null}
          {invalid ? <p className="field-error">Use PDF, PNG or JPEG files only.</p> : null}
          {mutation.error ? <p className="field-error" role="alert">{errorMessage(mutation.error)}</p> : null}
          <div className="form-actions">
            <button className="button button-primary" disabled={!invoice || Boolean(invalid) || mutation.isPending} onClick={() => mutation.mutate()}>
              {mutation.isPending ? "Processing case…" : "Process case"}
            </button>
          </div>
        </section>
        <aside className="card stack">
          <div className="card-header"><h2>Case readiness</h2></div>
          <div className="case-readiness">
            <strong>Durable workflow</strong>
            <span>Invoice <b>{readiness.invoice}</b></span>
            <span>Purchase order <b>{readiness.purchaseOrder}</b></span>
            <span>Receipt evidence <b>{readiness.receipts}</b></span>
          </div>
          {createdCase ? <p className="notice"><strong>{createdCase.case_number}</strong>The case already exists. Retrying reuses accepted attachments.</p> : null}
          <p className="help-text">Document role is selected by you; InvoiceOps does not claim automatic classification. Matching remains deterministic and no outcome authorizes payment.</p>
        </aside>
      </div>
    </>
  );
}

function UploadPanel({ id, title, hint, role, multiple = false, onFiles }: { id: string; title: string; hint: string; role: Role; multiple?: boolean; onFiles: (role: Role, files: FileList | null) => void }) {
  return <div className="upload-panel"><div><strong>{title}</strong><span>{hint}</span></div><label className="button button-secondary" htmlFor={id}><FilePlus2 aria-hidden="true"/>Add file</label><input id={id} className="visually-hidden" type="file" multiple={multiple} accept="application/pdf,image/png,image/jpeg" onChange={(event) => onFiles(role, event.target.files)}/></div>;
}

function FileCard({ item, remove, retry }: { item: PendingDocument; remove: () => void; retry: () => void }) {
  return <div className="file-row"><div className="file-role-icon">{item.state === "accepted" ? <FileCheck2/> : <FileUp/>}</div><div className="file-copy"><strong>{item.file.name}</strong><span>{item.role.replaceAll("_", " ")} · {item.file.type} · {(item.file.size / 1024).toFixed(1)} KiB</span>{item.state === "uploading" ? <progress value={item.progress} max="100" aria-label={`${item.file.name} upload progress`}/> : null}{item.error ? <small className="field-error">{item.error}</small> : null}</div><span className={`status ${item.state === "failed" ? "status-danger" : item.state === "accepted" ? "status-success" : "status-neutral"}`}>{item.state}</span>{item.state === "failed" ? <button className="icon-button" aria-label={`Retry ${item.file.name}`} onClick={retry}><RotateCcw/></button> : <button className="icon-button" aria-label={`Remove ${item.file.name}`} disabled={item.state === "accepted"} onClick={remove}><X/></button>}</div>;
}
