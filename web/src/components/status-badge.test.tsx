import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "./status-badge";

describe("StatusBadge", () => {
  it("uses visible text in addition to color", () => {
    render(<StatusBadge value="NEEDS_REVIEW" />);
    expect(screen.getByText("NEEDS REVIEW")).toHaveClass("status-warning");
  });
});
