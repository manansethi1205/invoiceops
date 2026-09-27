"use client";

import { useEffect, useRef, useState } from "react";

import { api, required } from "@/lib/api/client";
import { consumeJobEvents, mergeJobEvent, terminalEventTypes, type JobEvent } from "@/lib/job-events";
import { formatDate } from "@/lib/format";

export function JobTimeline({ jobId }: { jobId: string }) {
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [connection, setConnection] = useState<"connecting" | "live" | "reconnecting" | "fallback" | "complete">("connecting");
  const last = useRef<number | undefined>(undefined);
  useEffect(() => {
    const controller = new AbortController();
    const connect = async () => {
      let attempt = 0;
      while (!controller.signal.aborted) {
        let terminal = false;
        try {
          setConnection(attempt === 0 ? "connecting" : "reconnecting");
          await consumeJobEvents(jobId, (event) => {
            terminal = terminalEventTypes.has(event.event_type);
            last.current = Math.max(last.current ?? 0, event.sequence);
            setEvents((current) => mergeJobEvent(current, event));
            setConnection(terminal ? "complete" : "live");
          }, controller.signal, last.current);
          if (terminal || controller.signal.aborted) return;
        } catch {
          if (controller.signal.aborted) return;
        }
        try {
          const job = await required(api.GET("/v1/jobs/{job_id}", { params: { path: { job_id: jobId } } }));
          if (job.status === "succeeded" || job.status === "failed") {
            setConnection("fallback");
            return;
          }
        } catch {
          // The next durable replay attempt remains authoritative.
        }
        attempt += 1;
        await new Promise<void>((resolve) => {
          const timeout = window.setTimeout(resolve, Math.min(1000 * 2 ** (attempt - 1), 5000));
          controller.signal.addEventListener("abort", () => { window.clearTimeout(timeout); resolve(); }, { once: true });
        });
      }
    };
    void connect();
    return () => controller.abort();
  }, [jobId]);
  return <div className="timeline" aria-live="polite">
    <p className="stream-status"><span className={`health-dot ${connection === "live" || connection === "complete" ? "healthy" : ""}`} aria-hidden="true" />{connection === "fallback" ? "Live stream ended; final job status confirmed by API" : connection}</p>
    {events.map((event) => <div className="timeline-item" key={event.id}><span className="timeline-marker"/><div className="timeline-copy"><strong>{event.message}</strong><span>{event.stage} · {formatDate(event.occurred_at)}</span></div></div>)}
    {!events.length ? <p className="muted">Waiting for durable processing events…</p> : null}
  </div>;
}
