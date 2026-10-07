import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("@/lib/auth/resolve", () => ({
  resolveSession: vi.fn(async () => ({ subject: "synthetic-reviewer", roles: ["reviewer"] })),
}));

import { POST } from "./[...path]/route";

const context = { params: Promise.resolve({ path: ["v1", "cases"] }) };

describe("session-backed backend proxy", () => {
  beforeEach(() => {
    vi.stubEnv("WEB_AUTH_MODE", "development");
    vi.stubEnv("WEB_ENVIRONMENT", "local");
    vi.stubEnv("WEB_PUBLIC_ORIGIN", "http://127.0.0.1:3000");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("rejects a foreign-origin mutation without contacting the API", async () => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    const response = await POST(new NextRequest("http://127.0.0.1:3000/api/backend/v1/cases", {
      method: "POST", headers: { origin: "https://foreign.example" }, body: "{}",
    }), context);
    expect(response.status).toBe(403);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("forwards a same-origin mutation under the server-side session identity", async () => {
    const upstream = vi.fn(async (_url: URL, init: RequestInit) => {
      const headers = new Headers(init.headers);
      expect(headers.get("X-Reviewer-ID")).toBe("synthetic-reviewer");
      expect(headers.has("Authorization")).toBe(false);
      return Response.json({ ok: true }, { status: 201 });
    });
    vi.stubGlobal("fetch", upstream);
    const response = await POST(new NextRequest("http://127.0.0.1:3000/api/backend/v1/cases", {
      method: "POST", headers: {
        origin: "http://127.0.0.1:3000", "content-type": "application/json",
        authorization: "Bearer spoofed", "x-reviewer-id": "spoofed",
      }, body: "{}",
    }), context);
    expect(response.status).toBe(201);
    expect(upstream).toHaveBeenCalledTimes(1);
  });

  it("keeps an authorized same-origin document upload stream intact", async () => {
    const upstream = vi.fn(async (_url: URL, init: RequestInit) => {
      const headers = new Headers(init.headers);
      expect(headers.get("content-type")).toContain("multipart/form-data");
      expect(init.body).toBeTruthy();
      return Response.json({ accepted: true }, { status: 202 });
    });
    vi.stubGlobal("fetch", upstream);
    const multipart = [
      "--synthetic-boundary",
      'Content-Disposition: form-data; name="file"; filename="synthetic.pdf"',
      "Content-Type: application/pdf",
      "",
      "%PDF-1.4 synthetic",
      "--synthetic-boundary--",
      "",
    ].join("\r\n");
    const response = await POST(new NextRequest("http://127.0.0.1:3000/api/backend/v1/cases/id/documents", {
      method: "POST", headers: {
        origin: "http://127.0.0.1:3000",
        "content-type": "multipart/form-data; boundary=synthetic-boundary",
      }, body: multipart,
    }), { params: Promise.resolve({ path: ["v1", "cases", "id", "documents"] }) });
    expect(response.status).toBe(202);
    expect(upstream).toHaveBeenCalledTimes(1);
  });
});
