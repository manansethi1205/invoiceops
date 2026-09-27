import { describe, expect, it } from "vitest";

import { ApiError, errorMessage, sanitizeMessage } from "./client";

describe("API error presentation", () => {
  it("removes control characters and bounds untrusted detail", () => {
    const message = sanitizeMessage(`bad\n\u0000${"x".repeat(400)}`);
    expect(message).not.toMatch(/[\u0000-\u001f]/);
    expect(message).toHaveLength(300);
  });

  it("uses a safe fallback for unknown failures", () => {
    expect(errorMessage({ secret: "do not render" })).toBe("The request could not be completed. Try again.");
    expect(errorMessage(new ApiError("Conflict", 409))).toBe("Conflict");
  });
});
