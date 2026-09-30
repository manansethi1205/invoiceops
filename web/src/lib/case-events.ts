import { z } from "zod";

import { parseSseBlock } from "@/lib/job-events";

export const caseEventSchema = z.object({
  id: z.string().uuid(),
  case_id: z.string().uuid(),
  sequence: z.number().int().positive(),
  event_type: z.string().min(1),
  stage: z.string().min(1),
  status: z.string().min(1),
  message: z.string().min(1),
  document_id: z.string().uuid().nullable(),
  document_role: z.enum(["INVOICE", "PURCHASE_ORDER", "GOODS_RECEIPT", "DELIVERY_NOTE"]).nullable(),
  payload: z.record(z.string(), z.unknown()),
  occurred_at: z.string(),
});
export type CaseEvent = z.infer<typeof caseEventSchema>;

export function mergeCaseEvent(events: CaseEvent[], incoming: CaseEvent): CaseEvent[] {
  if (events.some((event) => event.id === incoming.id || event.sequence === incoming.sequence)) {
    return events;
  }
  return [...events, incoming].sort((left, right) => left.sequence - right.sequence);
}

export async function consumeCaseEvents(
  caseId: string,
  onEvent: (event: CaseEvent) => void,
  signal: AbortSignal,
  lastEventId?: number,
): Promise<void> {
  const response = await fetch(`/api/backend/v1/cases/${caseId}/events`, {
    headers: lastEventId === undefined ? {} : { "Last-Event-ID": String(lastEventId) },
    signal,
  });
  if (!response.ok || !response.body) throw new Error("The case event stream is unavailable");
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += value ?? "";
    let boundary = buffer.search(/\r?\n\r?\n/);
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      const separator = buffer.slice(boundary).match(/^\r?\n\r?\n/)?.[0].length ?? 2;
      buffer = buffer.slice(boundary + separator);
      const parsed = parseSseBlock(block);
      if (parsed?.event !== "heartbeat" && parsed?.data) {
        onEvent(caseEventSchema.parse(JSON.parse(parsed.data)));
      }
      boundary = buffer.search(/\r?\n\r?\n/);
    }
    if (done) return;
  }
}
