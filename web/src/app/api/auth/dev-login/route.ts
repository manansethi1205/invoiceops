import { NextRequest, NextResponse } from "next/server";

import { authMode, newDevelopmentSession, publicOrigin, sameOriginSubmission, SESSION_COOKIE, sessionCookieOptions, type AppRole } from "@/lib/auth/session";

const users: Record<string, AppRole[]> = {
  operator: ["operator"], reviewer: ["reviewer"], auditor: ["auditor"], admin: ["admin"],
};

export async function POST(request: NextRequest) {
  if (authMode() !== "development") return new Response(null, { status: 404 });
  if (!sameOriginSubmission(request)) return new Response(null, { status: 403 });
  const data = await request.formData();
  const role = data.get("role");
  if (typeof role !== "string" || !(role in users)) return new Response("Invalid synthetic role", { status: 400 });
  const id = newDevelopmentSession(role as AppRole);
  const response = NextResponse.redirect(new URL("/dashboard", publicOrigin(request)), 303);
  response.cookies.set(SESSION_COOKIE, id, sessionCookieOptions);
  return response;
}
