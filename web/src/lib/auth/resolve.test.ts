import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AppSession } from "./session";

vi.mock("server-only", () => ({}));
vi.mock("./oidc", () => ({
  oidcConfiguration: vi.fn(async () => ({})),
  oidc: { refreshTokenGrant: vi.fn() },
}));
vi.mock("./session", () => ({
  authMode: vi.fn(() => "oidc"),
  loadSession: vi.fn(),
  saveSession: vi.fn(),
}));

import { oidc } from "./oidc";
import { resolveSession } from "./resolve";
import { loadSession, saveSession } from "./session";

const expired: AppSession = {
  subject: "synthetic-reviewer",
  roles: ["reviewer"],
  accessToken: "old-access",
  refreshToken: "old-refresh",
  expiresAt: 0,
};

describe("OIDC session renewal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(loadSession).mockResolvedValue({ ...expired });
    vi.mocked(saveSession).mockResolvedValue();
  });

  it("coalesces concurrent refreshes and returns the rotated token to both requests", async () => {
    vi.mocked(oidc.refreshTokenGrant).mockResolvedValue({
      access_token: "new-access", refresh_token: "new-refresh", expires_in: 300,
    } as Awaited<ReturnType<typeof oidc.refreshTokenGrant>>);
    const [first, second] = await Promise.all([resolveSession("session-a"), resolveSession("session-a")]);
    expect(first?.accessToken).toBe("new-access");
    expect(second?.refreshToken).toBe("new-refresh");
    expect(oidc.refreshTokenGrant).toHaveBeenCalledTimes(1);
    expect(saveSession).toHaveBeenCalledTimes(1);
  });

  it("uses the newest Redis session instead of rotating stale credentials", async () => {
    vi.mocked(loadSession)
      .mockResolvedValueOnce({ ...expired })
      .mockResolvedValueOnce({ ...expired, accessToken: "already-renewed", expiresAt: Date.now() + 300_000 });
    const session = await resolveSession("session-b");
    expect(session?.accessToken).toBe("already-renewed");
    expect(oidc.refreshTokenGrant).not.toHaveBeenCalled();
  });

  it("fails closed when the provider cannot refresh", async () => {
    vi.mocked(oidc.refreshTokenGrant).mockRejectedValue(new Error("synthetic provider outage"));
    expect(await resolveSession("session-c")).toBeNull();
    expect(saveSession).not.toHaveBeenCalled();
  });
});
