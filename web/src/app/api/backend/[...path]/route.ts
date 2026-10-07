import { NextRequest } from "next/server";

import { resolveSession } from "@/lib/auth/resolve";
import { authMode, sameOriginSubmission, SESSION_COOKIE } from "@/lib/auth/session";

export const runtime = "nodejs";

const requestHeaders = ["accept", "content-type", "last-event-id", "idempotency-key", "if-match"];
const responseHeaders = ["content-type", "content-disposition", "etag", "last-event-id", "retry-after"];

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }): Promise<Response> {
  if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method) && !sameOriginSubmission(request)) {
    return Response.json({ detail: "Cross-origin mutation denied" }, { status: 403 });
  }
  const path = (await context.params).path;
  if (!path?.length || path.some((segment) => segment === ".." || segment.includes("/"))) return new Response(null, { status: 404 });
  let session;
  try { session = await resolveSession(request.cookies.get(SESSION_COOKIE)?.value); }
  catch { return Response.json({ detail: "Session unavailable" }, { status: 503 }); }
  if (!session) return Response.json({ detail: "Session required" }, { status: 401 });
  const backend = process.env.INVOICEOPS_API_URL ?? "http://127.0.0.1:8000";
  const url = new URL(path.map(encodeURIComponent).join("/"), `${backend.replace(/\/$/, "")}/`);
  url.search = request.nextUrl.search;
  const headers = new Headers();
  for (const name of requestHeaders) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (authMode() === "oidc") headers.set("Authorization", `Bearer ${session.accessToken}`);
  else {
    headers.set("X-Actor-ID", session.subject);
    headers.set("X-Reviewer-ID", session.subject);
    headers.set("X-Dev-Roles", session.roles.join(","));
  }
  try {
    const upstream = await fetch(url, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      // Streaming uploads and SSE must not be buffered by the BFF.
      duplex: "half",
      cache: "no-store",
    } as RequestInit & { duplex: "half" });
    const output = new Headers({ "Cache-Control": "no-store" });
    for (const name of responseHeaders) {
      const value = upstream.headers.get(name);
      if (value) output.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: output });
  } catch {
    return Response.json({ detail: "Backend unavailable" }, { status: 502 });
  }
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE, proxy as HEAD };
