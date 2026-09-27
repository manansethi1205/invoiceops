import { describe, expect, it } from "vitest";

import { jobEventSchema, mergeJobEvent, parseSseBlock, terminalEventTypes } from "./job-events";

describe("durable job events", () => {
  it("parses an SSE frame without conflating event and payload", () => {
    const parsed = parseSseBlock('id: 3\nevent: processing.completed\ndata: {"sequence":3}');
    expect(parsed).toEqual({ id: "3", event: "processing.completed", data: '{"sequence":3}' });
  });

  it("rejects malformed event payloads at the trust boundary", () => {
    expect(() => jobEventSchema.parse({ event_type: "processing.completed" })).toThrow();
  });

  it("orders replayed events and ignores duplicate IDs or sequences", () => {
    const second = jobEventSchema.parse({ id: "00000000-0000-4000-8000-000000000002", job_id: "00000000-0000-4000-8000-000000000001", sequence: 2, event_type: "document.validated", stage: "validation", status: "completed", message: "Validated", occurred_at: "2026-09-27T00:00:00Z", trace_id: null, payload: {} });
    const first = { ...second, id: "00000000-0000-4000-8000-000000000003", sequence: 1, event_type: "upload.accepted" as const };
    const ordered = mergeJobEvent(mergeJobEvent([], second), first);
    expect(ordered.map((event) => event.sequence)).toEqual([1, 2]);
    expect(mergeJobEvent(ordered, second)).toBe(ordered);
  });

  it("closes the stream only for durable completion or failure", () => {
    expect(terminalEventTypes.has("processing.completed")).toBe(true);
    expect(terminalEventTypes.has("processing.failed")).toBe(true);
    expect(terminalEventTypes.has("extraction.completed")).toBe(false);
  });
});
