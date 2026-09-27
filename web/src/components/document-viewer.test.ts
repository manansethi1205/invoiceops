import { describe, expect, it } from "vitest";

import { bboxStyle } from "@/lib/evidence";

describe("evidence overlay", () => {
  it("converts normalized provenance coordinates to percentages", () => {
    expect(bboxStyle({ x0: 0.1, y0: 0.2, x1: 0.7, y1: 0.5 })).toEqual({
      left: "10%", top: "20%", width: "60%", height: "30%",
    });
  });
});
