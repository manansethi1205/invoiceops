"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { ErrorState, LoadingState } from "@/components/feedback";
import { InvoiceFields, invoiceFields } from "@/components/invoice-fields";
import { JobTimeline } from "@/components/job-timeline";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { api, errorMessage, required } from "@/lib/api/client";
import { formatDate, formatMoney } from "@/lib/format";

const DocumentViewer = dynamic(() => import("@/components/document-viewer").then((module) => module.DocumentViewer), { ssr: false, loading: () => <LoadingState label="Loading document viewer"/> });

export default function InvoiceDetailPage() {
  const { invoiceId } = useParams<{invoiceId:string}>();
  const search = useSearchParams();
  const queryClient = useQueryClient();
  const [poId,setPoId] = useState(search.get("po") ?? "");
  const [mode,setMode] = useState<"TWO_WAY"|"THREE_WAY">("TWO_WAY");
  const [selected,setSelected] = useState("invoice_number");
  const summary = useQuery({ queryKey:["invoice",invoiceId], queryFn:()=>required(api.GET("/v1/invoices/{document_id}",{params:{path:{document_id:invoiceId}}})) });
  const extraction = useQuery({ queryKey:["extraction",invoiceId], queryFn:()=>required(api.GET("/v1/invoices/{document_id}/extraction",{params:{path:{document_id:invoiceId}}})), refetchInterval:(query)=>query.state.data?.status === "processing" ? 1500 : false });
  const purchaseOrders = useQuery({ queryKey:["purchase-orders"], queryFn:()=>required(api.GET("/v1/purchase-orders",{params:{query:{limit:100}}})) });
  const match = useQuery({ queryKey:["match",summary.data?.latest_match_run_id], enabled:Boolean(summary.data?.latest_match_run_id), queryFn:()=>required(api.GET("/v1/matches/{match_run_id}",{params:{path:{match_run_id:summary.data!.latest_match_run_id!}}})) });
  const risk = useQuery({ queryKey:["risk",summary.data?.latest_match_run_id], enabled:Boolean(summary.data?.latest_match_run_id), queryFn:()=>required(api.GET("/v1/matches/{match_run_id}/risk",{params:{path:{match_run_id:summary.data!.latest_match_run_id!}}})) });
  const createMatch = useMutation({ mutationFn:()=>required(api.POST("/v1/documents/{document_id}/matches",{params:{path:{document_id:invoiceId}},body:{purchase_order_id:poId,mode}})), onSuccess: async()=>{await queryClient.invalidateQueries({queryKey:["invoice",invoiceId]});} });
  const invoice = extraction.data && "invoice" in extraction.data ? extraction.data.invoice : null;
  const fields = useMemo(()=>invoice ? invoiceFields(invoice) : [],[invoice]);
  const evidence = fields.find((field)=>field.key===selected)?.evidence ?? [];
  if(summary.isLoading || extraction.isLoading) return <LoadingState label="Loading invoice workspace"/>;
  if(summary.error || extraction.error) return <ErrorState message={errorMessage(summary.error ?? extraction.error)} retry={()=>{void summary.refetch();void extraction.refetch();}}/>;
  if(!summary.data) return null;
  return <><PageHeader eyebrow="Invoice workspace" title={summary.data.invoice_number ?? summary.data.filename} description={`Received ${formatDate(summary.data.created_at)} · ${formatMoney(summary.data.total,summary.data.currency)}`} action={<StatusBadge value={summary.data.match_decision ?? summary.data.job_status}/>}/>
    <div className="workspace-grid"><section>{invoice ? <DocumentViewer documentId={invoiceId} contentType={summary.data.content_type} evidence={evidence}/> : <div className="card"><JobTimeline jobId={summary.data.job_id}/></div>}</section><aside className="stack">
      <section className="card"><div className="card-header"><h2>Extracted fields</h2>{extraction.data && "used_ocr" in extraction.data ? <span className="muted">{extraction.data.used_ocr ? "OCR used" : "Embedded text"}</span>:null}</div>{invoice ? <InvoiceFields fields={fields} selected={selected} onSelect={setSelected}/> : <p className="muted">Extraction is {extraction.data?.status}.</p>}</section>
      {invoice?.line_items.length ? <section className="card"><div className="card-header"><h2>Line items</h2><span className="muted">{invoice.line_items.length} rows</span></div><table className="data-table"><thead><tr><th>Description</th><th>Qty</th><th>Price</th><th>Total</th></tr></thead><tbody>{invoice.line_items.map((line,index)=><tr key={index}><td>{line.description.value ?? "—"}</td><td>{line.quantity.value ?? "—"}</td><td>{line.unit_price.value ?? "—"}</td><td>{line.line_total.value ?? "—"}</td></tr>)}</tbody></table></section>:null}
      <section className="card"><div className="card-header"><h2>Deterministic match</h2><StatusBadge value={match.data?.decision ?? summary.data.match_decision}/></div>{match.data ? <><p><strong>{match.data.result.summary.passed_check_count}</strong> checks passed · <strong>{match.data.result.summary.failed_check_count}</strong> failed</p>{match.data.result.reason_codes.length ? <p className="notice"><strong>Review reasons</strong>{match.data.result.reason_codes.join(", ")}</p>:null}{match.data.review_case_id ? <Link className="button button-primary" href={`/reviews/${match.data.review_case_id}`}>Open review case</Link>:null}<p className="help-text">A match result and risk disposition do not authorize payment.</p></> : <><div className="field"><label htmlFor="po">Purchase order</label><select id="po" value={poId} onChange={(event)=>setPoId(event.target.value)}><option value="">Select a PO</option>{purchaseOrders.data?.map((po)=><option value={po.id} key={po.id}>{po.external_po_number} · {po.currency}</option>)}</select></div><div className="field"><label htmlFor="mode">Matching mode</label><select id="mode" value={mode} onChange={(event)=>setMode(event.target.value as typeof mode)}><option value="TWO_WAY">Two-way</option><option value="THREE_WAY">Three-way</option></select></div>{createMatch.error ? <p className="field-error">{errorMessage(createMatch.error)}</p>:null}<div className="form-actions"><button className="button button-primary" disabled={!poId || createMatch.isPending || extraction.data?.status!=="succeeded"} onClick={()=>createMatch.mutate()}>Run match</button></div></>}</section>
      {match.data?.result.checks.some((check)=>check.status==="failed") ? <section className="card"><div className="card-header"><h2>Failed checks</h2></div><div className="check-list">{match.data.result.checks.filter((check)=>check.status==="failed").map((check,index)=><div className="check-row" key={`${check.code}-${index}`}><strong>{check.code}</strong><span>{check.message}</span><code>actual {check.actual ?? "—"} · expected {check.expected ?? "—"} · tolerance {check.tolerance ?? "—"}</code></div>)}</div></section>:null}
      {risk.data ? <section className="card"><div className="card-header"><h2>Duplicate risk</h2><StatusBadge value={risk.data.disposition}/></div>{risk.data.signals.length ? <div className="check-list">{risk.data.signals.map((signal)=><div className="check-row" key={signal.id}><strong>{signal.code}</strong><span>{signal.explanation}</span><code>severity {signal.severity}</code></div>)}</div>:<p className="muted">No duplicate-risk signals were emitted.</p>}<details><summary>Technical policy details</summary><pre className="technical-json">{JSON.stringify({policy:risk.data.policy_snapshot,candidate_metrics:risk.data.candidate_metrics},null,2)}</pre></details></section>:null}
      <section className="card"><div className="card-header"><h2>Processing history</h2></div><JobTimeline jobId={summary.data.job_id}/></section>
    </aside></div>
  </>;
}
