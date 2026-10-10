import { describe, expect, it } from "vitest";

import { reviewReasonExplanation, reviewReasonLabel, rowAssociationReason } from "./review-reasons";

describe("review reason presentation", () => {
  it("explains unresolved row association without suggesting payment authority", () => {
    expect(reviewReasonLabel(rowAssociationReason.code)).toBe("Invoice row association needs review");
    expect(reviewReasonExplanation(rowAssociationReason.code)).toContain("Automatic matching was withheld");
    expect(reviewReasonExplanation(rowAssociationReason.code)).toContain("source document");
  });

  it("preserves other reason codes without inventing an explanation", () => {
    expect(reviewReasonLabel("CURRENCY_MISMATCH")).toBe("CURRENCY_MISMATCH");
    expect(reviewReasonExplanation("CURRENCY_MISMATCH")).toBeUndefined();
  });
});
