import { NextRequest, NextResponse } from "next/server";

import { oidc, oidcConfiguration } from "@/lib/auth/oidc";
import { consumeLoginState, newSessionId, publicOrigin, saveSession, SESSION_COOKIE, sessionCookieOptions } from "@/lib/auth/session";
import type { components } from "@/lib/api/schema";

export async function GET(request: NextRequest) {
  const url = new URL(`${request.nextUrl.pathname}${request.nextUrl.search}`, publicOrigin(request));
  const state = url.searchParams.get("state");
  const cookieState = request.cookies.get("invoiceops_oidc_state")?.value;
  if (!state || state !== cookieState || url.searchParams.has("error")) return NextResponse.redirect(new URL("/provider-error", publicOrigin(request)));
  try {
    const login = await consumeLoginState(state);
    if (!login) return NextResponse.redirect(new URL("/provider-error", publicOrigin(request)));
    const tokens = await oidc.authorizationCodeGrant(await oidcConfiguration(), url, {
      pkceCodeVerifier: login.verifier,
      expectedState: state,
      expectedNonce: login.nonce,
      idTokenExpected: true,
    });
    const principalResponse = await fetch(`${process.env.INVOICEOPS_API_URL ?? "http://127.0.0.1:8000"}/v1/me`, {
      headers: { authorization: `Bearer ${tokens.access_token}` }, cache: "no-store",
    });
    if (!principalResponse.ok) return NextResponse.redirect(new URL("/forbidden", publicOrigin(request)));
    const principal: components["schemas"]["PrincipalRead"] = await principalResponse.json();
    const id = newSessionId();
    await saveSession(id, {
      subject: principal.subject,
      roles: principal.roles,
      accessToken: tokens.access_token,
      refreshToken: tokens.refresh_token,
      expiresAt: Date.now() + (tokens.expires_in ?? 300) * 1000,
    });
    const response = NextResponse.redirect(new URL("/dashboard", publicOrigin(request)));
    response.cookies.set(SESSION_COOKIE, id, sessionCookieOptions);
    response.cookies.delete("invoiceops_oidc_state");
    return response;
  } catch {
    return NextResponse.redirect(new URL("/provider-error", publicOrigin(request)));
  }
}
