import { NextRequest, NextResponse } from "next/server";

import { deleteSession, publicOrigin, sameOriginSubmission, SESSION_COOKIE } from "@/lib/auth/session";

export async function POST(request: NextRequest) {
  if (!sameOriginSubmission(request)) return new Response(null, { status: 403 });
  await deleteSession(request.cookies.get(SESSION_COOKIE)?.value);
  const response = NextResponse.redirect(new URL("/login", publicOrigin(request)), 303);
  response.cookies.delete(SESSION_COOKIE);
  return response;
}
