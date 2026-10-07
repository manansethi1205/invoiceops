import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("./session", () => ({ authMode: vi.fn(() => "oidc") }));
vi.mock("openid-client", () => ({
  discovery: vi.fn(async (issuer: URL) => ({ serverMetadata: () => ({ issuer: issuer.href }) })),
  allowInsecureRequests: vi.fn(),
}));

import * as oidc from "openid-client";

describe("OIDC discovery transport", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    vi.stubEnv("OIDC_CLIENT_ID", "synthetic-web");
    vi.stubEnv("OIDC_CLIENT_SECRET", "synthetic-local-only");
  });

  afterEach(() => vi.unstubAllEnvs());

  it("permits HTTP only for the non-production localhost smoke issuer", async () => {
    vi.stubEnv("WEB_ENVIRONMENT", "local");
    vi.stubEnv("OIDC_ISSUER", "http://localhost:8080/realms/invoiceops");
    const { oidcConfiguration } = await import("./oidc");
    await oidcConfiguration();
    expect(vi.mocked(oidc.discovery).mock.calls[0]?.[4]).toEqual({
      execute: [oidc.allowInsecureRequests],
    });
  });

  it("rejects non-loopback HTTP without attempting discovery", async () => {
    vi.stubEnv("WEB_ENVIRONMENT", "local");
    vi.stubEnv("OIDC_ISSUER", "http://identity.example/realms/invoiceops");
    const { oidcConfiguration } = await import("./oidc");
    await expect(oidcConfiguration()).rejects.toThrow("HTTPS");
    expect(oidc.discovery).not.toHaveBeenCalled();
  });

  it("rejects localhost HTTP in production", async () => {
    vi.stubEnv("WEB_ENVIRONMENT", "production");
    vi.stubEnv("OIDC_ISSUER", "http://localhost:8080/realms/invoiceops");
    const { oidcConfiguration } = await import("./oidc");
    await expect(oidcConfiguration()).rejects.toThrow("HTTPS");
  });
});
