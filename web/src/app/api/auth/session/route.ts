import { NextRequest } from "next/server";

import { resolveSession } from "@/lib/auth/resolve";
import { SESSION_COOKIE } from "@/lib/auth/session";

export async function GET(request: NextRequest) {
  try {
    const session = await resolveSession(request.cookies.get(SESSION_COOKIE)?.value);
    if (!session) return Response.json({ detail: "Session expired" }, { status: 401 });
    return Response.json({ subject: session.subject, roles: session.roles }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ detail: "Session unavailable" }, { status: 503 });
  }
}
