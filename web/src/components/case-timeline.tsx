"use client";

import { useEffect, useRef, useState } from "react";

import { consumeCaseEvents, mergeCaseEvent, type CaseEvent } from "@/lib/case-events";
import { formatDate } from "@/lib/format";

export function CaseTimeline({ caseId }: { caseId: string }) {
  const [events, setEvents] = useState<CaseEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const last = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    let reconnect: ReturnType<typeof setTimeout> | undefined;
    const connect = async () => {
      try {
        setConnected(true);
        await consumeCaseEvents(caseId, (event) => {
          last.current = Math.max(last.current, event.sequence);
          setEvents((current) => mergeCaseEvent(current, event));
        }, controller.signal, last.current || undefined);
      } catch {
        if (!controller.signal.aborted) reconnect = setTimeout(() => void connect(), 1200);
      } finally {
        setConnected(false);
      }
    };
    void connect();
    return () => { controller.abort(); if (reconnect) clearTimeout(reconnect); };
  }, [caseId]);
  return <div className="stack"><span className="stream-status"><span className={`health-dot ${connected ? "healthy" : "unhealthy"}`}/>{connected ? "Live" : "Reconnecting"}</span><div className="timeline">{events.map((event) => <div className="timeline-item" key={event.id}><span className="timeline-marker"/><div className="timeline-copy"><strong>{event.message}</strong><span>{event.document_role?.replaceAll("_", " ") ?? "CASE"} · {event.stage} · {formatDate(event.occurred_at)}</span></div></div>)}</div></div>;
}
