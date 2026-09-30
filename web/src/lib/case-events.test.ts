import { describe, expect, it } from "vitest";

import { caseEventSchema, mergeCaseEvent } from "./case-events";

const event = {
  id: "00000000-0000-4000-8000-000000000001",
  case_id: "00000000-0000-4000-8000-000000000002",
  sequence: 1,
  event_type: "UPLOAD_ACCEPTED",
  stage: "upload",
  status: "completed",
  message: "Case document attached",
  document_id: "00000000-0000-4000-8000-000000000003",
  document_role: "PURCHASE_ORDER" as const,
  payload: { filename: "synthetic-po.pdf" },
  occurred_at: "2026-09-30T00:00:00Z",
};

describe("case events", () => {
  it("validates privacy-bounded role-aware events", () => {
    expect(caseEventSchema.parse(event).document_role).toBe("PURCHASE_ORDER");
  });

  it("deduplicates replayed sequence numbers", () => {
    expect(mergeCaseEvent([event], { ...event, id: "00000000-0000-4000-8000-000000000004" })).toEqual([event]);
  });

  it("rejects unrecognized document roles", () => {
    expect(() => caseEventSchema.parse({ ...event, document_role: "BANK_STATEMENT" })).toThrow();
  });
});
