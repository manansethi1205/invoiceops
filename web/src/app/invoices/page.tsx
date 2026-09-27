"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { EmptyState, ErrorState, LoadingState } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { api, errorMessage, required } from "@/lib/api/client";
import { formatDate, formatMoney } from "@/lib/format";

export default function InvoicesPage() {
  const query = useQuery({ queryKey: ["invoices"], queryFn: () => required(api.GET("/v1/invoices", { params: { query: { limit: 100 } } })) });
  if (query.isLoading) return <LoadingState label="Loading invoices" />;
  if (query.error) return <ErrorState message={errorMessage(query.error)} retry={() => void query.refetch()} />;
  return <><PageHeader eyebrow="Document register" title="Invoices" description="Every uploaded document, its extraction state and downstream decision references." action={<Link href="/intake" className="button button-primary">New intake</Link>} />
    <section className="card">{query.data?.items.length ? <table className="data-table"><thead><tr><th>Document</th><th>Invoice number</th><th>Amount</th><th>Received</th><th>Job</th><th>Decision</th></tr></thead><tbody>{query.data.items.map((item) => <tr key={item.document_id}><td><Link href={`/invoices/${item.document_id}`}>{item.filename}</Link><div className="mono muted">{item.document_id}</div></td><td>{item.invoice_number ?? "—"}</td><td>{formatMoney(item.total,item.currency)}</td><td>{formatDate(item.created_at)}</td><td><StatusBadge value={item.job_status}/></td><td><StatusBadge value={item.match_decision}/></td></tr>)}</tbody></table> : <EmptyState title="No invoices found" detail="The register will populate after the first upload." />}</section>
  </>;
}
