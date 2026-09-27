"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { EmptyState, ErrorState, LoadingState } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { api, errorMessage, required } from "@/lib/api/client";
import { ageSince, formatDate, formatMoney } from "@/lib/format";

export default function DashboardPage() {
  const summary = useQuery({ queryKey: ["dashboard"], queryFn: () => required(api.GET("/v1/dashboard/summary")) });
  const invoices = useQuery({ queryKey: ["invoices", "recent"], queryFn: () => required(api.GET("/v1/invoices", { params: { query: { limit: 8 } } })) });
  if (summary.isLoading || invoices.isLoading) return <LoadingState label="Loading operational summary" />;
  if (summary.error || invoices.error) return <ErrorState message={errorMessage(summary.error ?? invoices.error)} retry={() => { void summary.refetch(); void invoices.refetch(); }} />;
  const data = summary.data;
  return <>
    <PageHeader eyebrow="Operations overview" title="Invoices moving with evidence" description="Measured queue state from the InvoiceOps API. Matching, risk and human resolution remain separate decisions." action={<Link href="/intake" className="button button-primary">Process invoice</Link>} />
    <section className="metric-grid" aria-label="Operational metrics">
      <div className="metric-card"><span>Documents received</span><strong>{data?.documents_total ?? 0}</strong></div>
      <div className="metric-card"><span>Processing now</span><strong>{data?.jobs_processing ?? 0}</strong></div>
      <div className="metric-card"><span>Waiting reviews</span><strong>{data?.reviews_waiting ?? 0}</strong></div>
      <div className="metric-card"><span>Oldest waiting</span><strong>{ageSince(data?.oldest_waiting_review_opened_at ?? null)}</strong></div>
    </section>
    <section className="card">
      <div className="card-header"><h2>Recent invoices</h2><Link href="/invoices" className="button button-secondary">View all</Link></div>
      {invoices.data?.items.length ? <div className="table-scroll"><table className="data-table"><thead><tr><th>Invoice</th><th>Received</th><th>Amount</th><th>Processing</th><th>Match</th><th>Review</th></tr></thead><tbody>{invoices.data.items.map((item) => <tr key={item.document_id}><td><Link href={`/invoices/${item.document_id}`}>{item.invoice_number ?? item.filename}</Link><div className="muted mono">{item.document_id.slice(0,8)}</div></td><td>{formatDate(item.created_at)}</td><td>{formatMoney(item.total,item.currency)}</td><td><StatusBadge value={item.job_status}/></td><td><StatusBadge value={item.match_decision}/></td><td><StatusBadge value={item.review_status}/></td></tr>)}</tbody></table></div> : <EmptyState title="No invoices yet" detail="Upload a synthetic or de-identified invoice to start the pipeline." />}
    </section>
  </>;
}
