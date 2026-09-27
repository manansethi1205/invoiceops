"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { FileUp, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { JobTimeline } from "@/components/job-timeline";
import { PageHeader } from "@/components/page-header";
import { api, errorMessage, required, uploadInvoice, type ApiSchema } from "@/lib/api/client";

export const intakeSchema = z.object({
  invoice: z.instanceof(File).refine((file) => ["application/pdf", "image/png", "image/jpeg"].includes(file.type), "Use PDF, PNG or JPEG").refine((file) => file.size <= 15 * 1024 * 1024, "File must be 15 MiB or smaller"),
  createPo: z.boolean(),
  createReceipt: z.boolean(),
  poNumber: z.string(), vendorName: z.string(), currency: z.string(), description: z.string(), quantity: z.string(), unitPrice: z.string(),
  receiptNumber: z.string(), receivedAt: z.string(), receivedQuantity: z.string(),
}).superRefine((value, context) => {
  if (value.createPo) for (const key of ["poNumber", "currency", "description", "quantity", "unitPrice"] as const) if (!value[key].trim()) context.addIssue({ code: "custom", path: [key], message: "Required when creating a PO" });
  if (value.createReceipt && !value.createPo) context.addIssue({ code: "custom", path: ["createReceipt"], message: "A receipt requires a purchase order" });
  if (value.createReceipt) for (const key of ["receiptNumber", "receivedAt", "receivedQuantity"] as const) if (!value[key].trim()) context.addIssue({ code: "custom", path: [key], message: "Required when adding a receipt" });
});
type FormValues = z.infer<typeof intakeSchema>;

export default function IntakePage() {
  const router = useRouter();
  const [accepted, setAccepted] = useState<ApiSchema<"UploadAccepted"> | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const form = useForm<FormValues>({ resolver: zodResolver(intakeSchema), defaultValues: { createPo: false, createReceipt: false, poNumber: "", vendorName: "", currency: "INR", description: "", quantity: "", unitPrice: "", receiptNumber: "", receivedAt: "", receivedQuantity: "" } });
  const createPo = useWatch({ control: form.control, name: "createPo" });
  const createReceipt = useWatch({ control: form.control, name: "createReceipt" });
  const invoice = useWatch({ control: form.control, name: "invoice" });
  const submit = form.handleSubmit(async (values) => {
    setFailure(null);
    try {
      const upload = await uploadInvoice(values.invoice);
      setAccepted(upload);
      let poId: string | null = null;
      if (values.createPo) {
        const po = await required(api.POST("/v1/purchase-orders", { body: { external_po_number: values.poNumber, vendor_name: values.vendorName || null, currency: values.currency, lines: [{ line_number: "1", description: values.description, ordered_quantity: values.quantity, unit_price: values.unitPrice }] } }));
        poId = po.id;
        const poLine = po.lines[0];
        if (values.createReceipt && !poLine) throw new Error("The created purchase order has no line to receive");
        if (values.createReceipt && poLine) await required(api.POST("/v1/goods-receipts", { body: { purchase_order_id: po.id, external_receipt_number: values.receiptNumber, received_at: new Date(values.receivedAt).toISOString(), lines: [{ purchase_order_line_id: poLine.id, accepted_quantity: values.receivedQuantity }] } }));
      }
      window.setTimeout(() => router.push(`/invoices/${upload.document_id}${poId ? `?po=${poId}` : ""}`), 900);
    } catch (error) { setFailure(errorMessage(error)); }
  });
  return <><PageHeader eyebrow="Controlled intake" title="Process an invoice" description="Upload one invoice and optionally create the structured purchase order used by deterministic matching. Supporting documents are not treated as extracted files because that backend does not exist yet." />
    <div className="two-column"><form className="card" onSubmit={submit} noValidate><div className="stack">
      <div className="dropzone" onDragOver={(event)=>event.preventDefault()} onDrop={(event)=>{event.preventDefault();const file=event.dataTransfer.files[0];if(file)form.setValue("invoice",file,{shouldValidate:true});}}><FileUp aria-hidden="true"/><strong>{invoice ? "Replace invoice" : "Upload invoice — required"}</strong><span>Drop a PDF, PNG or JPEG here, or use the keyboard-accessible file picker · up to 15 MiB</span><label className="button button-secondary" htmlFor="invoice-file">{invoice ? "Replace file" : "Browse files"}</label><input id="invoice-file" type="file" accept="application/pdf,image/png,image/jpeg" onChange={(event) => { const file=event.target.files?.[0]; if(file)form.setValue("invoice",file,{shouldValidate:true}); }}/></div>
      {invoice ? <div className="file-row"><div><strong>{invoice.name}</strong><span>{invoice.type} · {(invoice.size/1024).toFixed(1)} KiB · ready</span></div><button type="button" className="icon-button" aria-label="Remove invoice" onClick={()=>form.resetField("invoice")}><X/></button></div>:null}
      {form.formState.errors.invoice ? <span className="field-error">{form.formState.errors.invoice.message}</span> : null}
      <label className="inline"><input type="checkbox" {...form.register("createPo")}/><strong>Create a structured purchase order</strong></label>
      {createPo ? <div className="form-grid"><Field label="PO number" error={form.formState.errors.poNumber?.message}><input {...form.register("poNumber")}/></Field><Field label="Vendor" error={form.formState.errors.vendorName?.message}><input {...form.register("vendorName")}/></Field><Field label="Currency" error={form.formState.errors.currency?.message}><input maxLength={3} {...form.register("currency")}/></Field><Field label="Line description" error={form.formState.errors.description?.message}><input {...form.register("description")}/></Field><Field label="Quantity" error={form.formState.errors.quantity?.message}><input inputMode="decimal" {...form.register("quantity")}/></Field><Field label="Unit price" error={form.formState.errors.unitPrice?.message}><input inputMode="decimal" {...form.register("unitPrice")}/></Field></div> : null}
      <label className="inline"><input type="checkbox" {...form.register("createReceipt")}/><strong>Add structured receipt / delivery proof</strong></label>
      {form.formState.errors.createReceipt ? <span className="field-error">{form.formState.errors.createReceipt.message}</span>:null}
      {createReceipt ? <div className="form-grid"><Field label="Receipt number" error={form.formState.errors.receiptNumber?.message}><input {...form.register("receiptNumber")}/></Field><Field label="Received at" error={form.formState.errors.receivedAt?.message}><input type="datetime-local" {...form.register("receivedAt")}/></Field><Field label="Accepted quantity" error={form.formState.errors.receivedQuantity?.message}><input inputMode="decimal" {...form.register("receivedQuantity")}/></Field></div>:null}
      {failure ? <p className="field-error" role="alert">{failure}</p> : null}
      <div className="case-readiness"><strong>Case readiness</strong><span>Invoice <b>{invoice ? "ready" : "required"}</b></span><span>Purchase order <b>{createPo ? "included" : "not included"}</b></span><span>Receipt <b>{createReceipt ? "included" : "not included"}</b></span></div>
      <div className="form-actions"><button className="button button-primary" disabled={!invoice || form.formState.isSubmitting}>{form.formState.isSubmitting ? "Submitting…" : "Begin processing"}</button></div>
    </div></form><aside className="card"><div className="card-header"><h2>Processing activity</h2></div>{accepted ? <><p className="notice"><strong>Upload accepted</strong>Document {accepted.deduplicated ? "matched existing work" : "entered the queue"}.</p><div className="divider"/><JobTimeline jobId={accepted.job_id}/></> : <p className="muted">Durable processing events will appear here after upload.</p>}</aside></div>
  </>;
}

function Field({ label, error, children }: { label: string; error?: string; children: React.ReactNode }) { return <div className="field"><label>{label}</label>{children}{error ? <small className="field-error">{error}</small> : null}</div>; }
