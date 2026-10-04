import { NextResponse } from "next/server";

import { oidc, oidcConfiguration, redirectUri } from "@/lib/auth/oidc";
import { authMode, publicOrigin, saveLoginState } from "@/lib/auth/session";

export async function GET(request: Request) {
  if (authMode() === "development") return NextResponse.redirect(new URL("/login", publicOrigin(request)));
  try {
    const configuration = await oidcConfiguration();
    const verifier = oidc.randomPKCECodeVerifier();
    const state = oidc.randomState();
    const nonce = oidc.randomNonce();
    await saveLoginState(state, verifier, nonce);
    const url = oidc.buildAuthorizationUrl(configuration, {
      redirect_uri: redirectUri(publicOrigin(request)),
      scope: "openid profile offline_access",
      code_challenge: await oidc.calculatePKCECodeChallenge(verifier),
      code_challenge_method: "S256",
      state,
      nonce,
    });
    const response = NextResponse.redirect(url);
    response.cookies.set("invoiceops_oidc_state", state, { httpOnly: true, secure: process.env.WEB_ENVIRONMENT === "production", sameSite: "lax", path: "/api/auth", maxAge: 300 });
    return response;
  } catch {
    return NextResponse.redirect(new URL("/provider-error", publicOrigin(request)));
  }
}
