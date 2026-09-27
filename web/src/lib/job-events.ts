import { z } from "zod";

export const jobEventSchema = z.object({
  id: z.string().uuid(),
  job_id: z.string().uuid(),
  sequence: z.number().int().positive(),
  event_type: z.enum(["upload.accepted", "document.validated", "extraction.started", "extraction.completed", "processing.completed", "processing.failed"]),
  stage: z.string(),
  status: z.string(),
  message: z.string(),
  occurred_at: z.string(),
  trace_id: z.string().nullable(),
  payload: z.record(z.string(), z.unknown()),
});
export type JobEvent = z.infer<typeof jobEventSchema>;
export const terminalEventTypes = new Set<JobEvent["event_type"]>([
  "processing.completed",
  "processing.failed",
]);

export function mergeJobEvent(events: JobEvent[], incoming: JobEvent): JobEvent[] {
  if (events.some((event) => event.id === incoming.id || event.sequence === incoming.sequence)) {
    return events;
  }
  return [...events, incoming].sort((left, right) => left.sequence - right.sequence);
}

export interface ParsedSseEvent {
  id?: string;
  event: string;
  data: string;
}

export function parseSseBlock(block: string): ParsedSseEvent | null {
  const parsed: ParsedSseEvent = { event: "message", data: "" };
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    const value = separator === -1 ? "" : line.slice(separator + 1).replace(/^ /, "");
    if (field === "id") parsed.id = value;
    if (field === "event") parsed.event = value;
    if (field === "data") data.push(value);
  }
  parsed.data = data.join("\n");
  return parsed.data || parsed.event !== "message" ? parsed : null;
}

export async function consumeJobEvents(
  jobId: string,
  onEvent: (event: JobEvent) => void,
  signal: AbortSignal,
  lastEventId?: number,
): Promise<void> {
  const response = await fetch(`/api/backend/v1/jobs/${jobId}/events`, {
    headers: lastEventId === undefined ? {} : { "Last-Event-ID": String(lastEventId) },
    signal,
  });
  if (!response.ok || !response.body) throw new Error("The processing stream is unavailable");
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
        onEvent(jobEventSchema.parse(JSON.parse(parsed.data)));
      }
      boundary = buffer.search(/\r?\n\r?\n/);
    }
    if (done) return;
  }
}
