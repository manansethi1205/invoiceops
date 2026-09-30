import { describe, expect, it } from "vitest";

import { LogicalActionIdempotencyKey } from "./idempotency";

describe("LogicalActionIdempotencyKey", () => {
  it("reuses confirmation and match keys across retries of the same payload", () => {
    let sequence = 0;
    const confirmation = new LogicalActionIdempotencyKey(() => `confirmation-${++sequence}`);
    const match = new LogicalActionIdempotencyKey(() => `match-${++sequence}`);
    const confirmationPayload = JSON.stringify({
      extractionRunId: "run-1",
      confirmed: { po_number: "PO-42" },
      correctionReason: null,
    });
    const matchPayload = JSON.stringify({ caseId: "case-1", expectedVersion: 4 });

    expect(confirmation.keyFor(confirmationPayload)).toBe("confirmation-1");
    expect(confirmation.keyFor(confirmationPayload)).toBe("confirmation-1");
    expect(match.keyFor(matchPayload)).toBe("match-2");
    expect(match.keyFor(matchPayload)).toBe("match-2");
  });

  it("rotates after a payload change, success, or explicit new action", () => {
    let sequence = 0;
    const keys = new LogicalActionIdempotencyKey(() => `key-${++sequence}`);

    expect(keys.keyFor("payload-a")).toBe("key-1");
    expect(keys.keyFor("payload-b")).toBe("key-2");
    keys.complete();
    expect(keys.keyFor("payload-b")).toBe("key-3");
    keys.beginNewAction();
    expect(keys.keyFor("payload-b")).toBe("key-4");
  });
});
