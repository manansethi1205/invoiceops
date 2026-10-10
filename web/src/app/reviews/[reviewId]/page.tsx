"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ErrorState, LoadingState } from "@/components/feedback";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { api, errorMessage, required, type ApiSchema } from "@/lib/api/client";
import { formatDate } from "@/lib/format";
import { reviewReasonExplanation, reviewReasonLabel } from "@/lib/review-reasons";

type Resolution = ApiSchema<"ReviewResolution">;
type ActionKind = "claim" | "release" | "comment" | "resolve";

export default function ReviewDetailPage() {
  const { reviewId } = useParams<{ reviewId: string }>();
  const cache = useQueryClient();
  const session = useQuery<{ subject: string; roles: string[] }>({ queryKey: ["auth-session"], queryFn: async () => (await fetch("/api/auth/session")).json() });
  const reviewer = session.data?.subject ?? "";
  const [comment, setComment] = useState("");
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [resolution, setResolution] = useState<Resolution>("ACCEPTED_EXCEPTION");
  const detail = useQuery({ queryKey: ["review", reviewId], queryFn: () => required(api.GET("/v1/review-cases/{case_id}", { params: { path: { case_id: reviewId } } })) });
  const events = useQuery({ queryKey: ["review-events", reviewId], queryFn: () => required(api.GET("/v1/review-cases/{case_id}/events", { params: { path: { case_id: reviewId } } })) });
  const audit = useQuery({ queryKey: ["review-audit", reviewId], queryFn: () => required(api.GET("/v1/review-cases/{case_id}/audit-verification", { params: { path: { case_id: reviewId } } })) });
  const refresh = async () => {
    await Promise.all([
      cache.invalidateQueries({ queryKey: ["review", reviewId] }),
      cache.invalidateQueries({ queryKey: ["review-events", reviewId] }),
      cache.invalidateQueries({ queryKey: ["review-audit", reviewId] }),
      cache.invalidateQueries({ queryKey: ["reviews"] }),
    ]);
  };
  const action = useMutation({
    mutationFn: async (kind: ActionKind) => {
      if (!detail.data) throw new Error("Case is not loaded");
      const common = { params: { path: { case_id: reviewId } } };
      if (kind === "claim") return required(api.POST("/v1/review-cases/{case_id}/claim", { ...common, body: { expected_version: detail.data.version } }));
      if (kind === "release") return required(api.POST("/v1/review-cases/{case_id}/release", { ...common, body: { expected_version: detail.data.version, reason } }));
      if (kind === "comment") return required(api.POST("/v1/review-cases/{case_id}/comments", { ...common, body: { expected_version: detail.data.version, comment } }));
      return required(api.POST("/v1/review-cases/{case_id}/resolve", { ...common, body: { expected_version: detail.data.version, resolution, reason } }));
    },
    onSuccess: async (_data, kind) => {
      setComment("");
      setReason("");
      if (kind === "resolve") setConfirming(false);
      await refresh();
    },
  });
  if (detail.isLoading) return <LoadingState label="Loading review case" />;
  if (detail.error || !detail.data) return <ErrorState message={errorMessage(detail.error)} retry={() => void detail.refetch()} />;
  const review = detail.data;
  const canReview = session.data?.roles.some((role) => ["reviewer", "admin"].includes(role)) ?? false;
  const canOwn = review.status === "OPEN" || review.assigned_reviewer_id === reviewer;
  return <>
    <PageHeader eyebrow="Human review" title={`Case ${review.id.slice(0, 8)}`} description={`Opened ${formatDate(review.opened_at)} · version ${review.version}`} action={<StatusBadge value={review.status} />} />
    <div className="two-column">
      <div className="stack">
        <section className="card"><div className="card-header"><h2>Decision context</h2><Link href={`/invoices/${review.match.document_id}`} className="button button-secondary">Inspect invoice</Link></div><p><strong>Match:</strong> <StatusBadge value={review.match.decision} /></p><p><strong>Risk:</strong> <StatusBadge value={review.match.risk_disposition} /></p><div className="notice"><strong>Why this needs attention</strong>{review.review_triggers.map((trigger) => <div key={trigger.id}><div>{trigger.type}: {reviewReasonLabel(trigger.code)}</div>{reviewReasonExplanation(trigger.code) ? <p>{reviewReasonExplanation(trigger.code)}</p> : null}</div>)}</div><p className="help-text">Accepting an exception records a review resolution. It does not authorize payment.</p></section>
        <section className="card"><div className="card-header"><h2>Tamper-evident history</h2><StatusBadge value={audit.data?.valid ? "CLEAR" : "failed"} /></div><div className="timeline">{events.data?.map((event) => <div className="timeline-item" key={event.id}><span className="timeline-marker" /><div className="timeline-copy"><strong>{event.event_type.replaceAll("_", " ")}</strong><span>{event.actor_id} · {formatDate(event.occurred_at)}</span><code className="mono">{event.event_hash.slice(0, 16)}… · {event.hash_version}</code></div></div>)}</div><p className="help-text">Hash chaining provides application-level tamper evidence; it does not prevent a database administrator from rewriting history.</p></section>
      </div>
      {canReview ? <aside className="card stack">
        <div><h2>Reviewer action</h2><p className="help-text">Actions are recorded under your verified session identity.</p></div>
        <p className="help-text">Signed in as {reviewer || "unknown"}</p>
        {review.status === "OPEN" ? <button className="button button-primary" disabled={!reviewer.trim() || action.isPending} onClick={() => action.mutate("claim")}>Claim case</button> : null}
        {review.status === "CLAIMED" ? <><div className="field"><label htmlFor="comment">Comment</label><textarea id="comment" value={comment} onChange={(event) => setComment(event.target.value)} rows={3} /></div><button className="button button-secondary" disabled={!comment.trim() || !canOwn || action.isPending} onClick={() => action.mutate("comment")}>Add comment</button><div className="field"><label htmlFor="resolution">Resolution</label><select id="resolution" value={resolution} onChange={(event) => setResolution(event.target.value as Resolution)}><option value="ACCEPTED_EXCEPTION">Accepted exception</option><option value="REJECTED_DOCUMENT">Rejected document</option><option value="CORRECTION_REQUESTED">Correction requested</option></select></div><div className="field"><label htmlFor="reason">Required explanation</label><textarea id="reason" value={reason} onChange={(event) => setReason(event.target.value)} rows={4} /></div><button className="button button-primary" disabled={!reason.trim() || !canOwn || action.isPending} onClick={() => setConfirming(true)}>Resolve case</button><button className="button button-secondary" disabled={!reason.trim() || !canOwn || action.isPending} onClick={() => action.mutate("release")}>Release to queue</button></> : null}
        {action.error ? <p className="field-error" role="alert">{errorMessage(action.error)}</p> : null}
      </aside> : null}
    </div>
    <Dialog.Root open={confirming} onOpenChange={setConfirming}><Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="dialog-content"><Dialog.Title>Confirm case resolution</Dialog.Title><Dialog.Description>This appends an immutable <strong>{resolution.replaceAll("_", " ")}</strong> resolution using case version {review.version}. It does not authorize payment.</Dialog.Description><div className="notice"><strong>Reviewer explanation</strong>{reason}</div>{action.error ? <p className="field-error" role="alert">{errorMessage(action.error)}</p> : null}<div className="form-actions"><Dialog.Close asChild><button className="button button-secondary">Cancel</button></Dialog.Close><button className="button button-primary" disabled={action.isPending} onClick={() => action.mutate("resolve")}>{action.isPending ? "Resolving…" : "Confirm resolution"}</button></div></Dialog.Content></Dialog.Portal></Dialog.Root>
  </>;
}
