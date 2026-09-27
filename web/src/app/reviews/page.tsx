"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { EmptyState, ErrorState, LoadingState } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { api, errorMessage, required, type ApiSchema } from "@/lib/api/client";
import { formatDate } from "@/lib/format";

type QueueStatus = "OPEN" | "CLAIMED" | "RESOLVED" | undefined;
type ReasonCode = ApiSchema<"ReasonCode">;

const statusOptions: ReadonlyArray<[QueueStatus, string]> = [[undefined, "All"], ["OPEN", "Open"], ["CLAIMED", "Claimed"], ["RESOLVED", "Resolved"]];
const reasonOptions: ReadonlyArray<[ReasonCode, string]> = [["CURRENCY_MISMATCH", "Currency mismatch"], ["INVOICE_TOTAL_MISMATCH", "Total mismatch"], ["QUANTITY_MISMATCH", "Quantity mismatch"], ["NO_GOODS_RECEIPT", "Missing receipt"], ["ALLOCATION_RECONCILIATION_REQUIRED", "Allocation reconciliation"]];

export default function ReviewsPage() {
  return <Suspense fallback={<LoadingState label="Loading review queue" />}><ReviewQueue /></Suspense>;
}

function ReviewQueue() {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const rawStatus = search.get("status");
  const status: QueueStatus = rawStatus === "OPEN" || rawStatus === "CLAIMED" || rawStatus === "RESOLVED" ? rawStatus : undefined;
  const assignee = search.get("assignee") || undefined;
  const rawReason = search.get("reason_code");
  const reasonCode = reasonOptions.some(([value]) => value === rawReason) ? rawReason as ReasonCode : undefined;
  const createdAfter = search.get("created_after") || undefined;
  const createdBefore = search.get("created_before") || undefined;
  const cursor = search.get("cursor") || undefined;
  const setFilter = (key: string, value?: string) => {
    const next = new URLSearchParams(search.toString());
    if (value) next.set(key, value); else next.delete(key);
    if (key !== "cursor") next.delete("cursor");
    router.replace(`${pathname}${next.size ? `?${next.toString()}` : ""}`);
  };
  const query = useQuery({
    queryKey: ["reviews", status, assignee, reasonCode, createdAfter, createdBefore, cursor],
    queryFn: () => required(api.GET("/v1/review-cases", { params: { query: { status, assignee, reason_code: reasonCode, created_after: createdAfter, created_before: createdBefore, cursor, limit: 50 } } })),
  });
  return <>
    <PageHeader eyebrow="Exception operations" title="Human review queue" description="Cases opened by deterministic matching or duplicate-risk signals. Human resolution remains distinct from payment authorization." action={<div className="segmented" aria-label="Filter review status">{statusOptions.map(([value, label]) => <button key={label} className={status === value ? "active" : ""} onClick={() => setFilter("status", value)}>{label}</button>)}</div>} />
    <section className="card filter-bar" aria-label="Review queue filters">
      <div className="field"><label htmlFor="assignee-filter">Assignee</label><input id="assignee-filter" value={assignee ?? ""} placeholder="reviewer ID" onChange={(event) => setFilter("assignee", event.target.value || undefined)} /></div>
      <div className="field"><label htmlFor="reason-filter">Reason</label><select id="reason-filter" value={reasonCode ?? ""} onChange={(event) => setFilter("reason_code", event.target.value || undefined)}><option value="">All reasons</option>{reasonOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
      <div className="field"><label htmlFor="after-filter">Opened after</label><input id="after-filter" type="datetime-local" value={createdAfter?.slice(0, 16) ?? ""} onChange={(event) => setFilter("created_after", event.target.value ? new Date(event.target.value).toISOString() : undefined)} /></div>
      <div className="field"><label htmlFor="before-filter">Opened before</label><input id="before-filter" type="datetime-local" value={createdBefore?.slice(0, 16) ?? ""} onChange={(event) => setFilter("created_before", event.target.value ? new Date(event.target.value).toISOString() : undefined)} /></div>
    </section>
    {query.isLoading ? <LoadingState label="Loading review queue" /> : query.error ? <ErrorState message={errorMessage(query.error)} retry={() => void query.refetch()} /> : <section className="card">{query.data?.items.length ? <><table className="data-table"><thead><tr><th>Case</th><th>Opened</th><th>Triggers</th><th>Owner</th><th>Status</th></tr></thead><tbody>{query.data.items.map((item) => <tr key={item.id}><td><Link href={`/reviews/${item.id}`}>Case {item.id.slice(0, 8)}</Link><div className="mono muted">Match {item.match_run_id.slice(0, 8)}</div></td><td>{formatDate(item.opened_at)}</td><td>{item.review_triggers.map((trigger) => <span className="status status-warning" key={trigger.id}>{trigger.code}</span>)}</td><td>{item.assigned_reviewer_id ?? "Unassigned"}</td><td><StatusBadge value={item.status} /></td></tr>)}</tbody></table><div className="form-actions"><button className="button button-secondary" disabled={!cursor} onClick={() => setFilter("cursor")}>First page</button><button className="button button-primary" disabled={!query.data.next_cursor} onClick={() => setFilter("cursor", query.data?.next_cursor ?? undefined)}>Next page</button></div></> : <EmptyState title="Queue is clear" detail="No review cases match these filters." />}</section>}
  </>;
}
