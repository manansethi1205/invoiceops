import "server-only";

import * as oidc from "openid-client";

import { authMode } from "./session";

let configuration: oidc.Configuration | undefined;

export async function oidcConfiguration(): Promise<oidc.Configuration> {
  if (authMode() !== "oidc") throw new Error("OIDC is not enabled");
  if (configuration) return configuration;
  const issuer = process.env.OIDC_ISSUER;
  const clientId = process.env.OIDC_CLIENT_ID;
  const clientSecret = process.env.OIDC_CLIENT_SECRET;
  if (!issuer || !clientId || !clientSecret) throw new Error("OIDC issuer and client credentials are required");
  const config = await oidc.discovery(new URL(issuer), clientId, clientSecret);
  if (config.serverMetadata().issuer !== issuer) throw new Error("OIDC issuer mismatch");
  configuration = config;
  return config;
}

export function redirectUri(origin: string): string {
  const configured = process.env.OIDC_REDIRECT_URI;
  if (configured) return configured;
  if (process.env.WEB_ENVIRONMENT === "production") throw new Error("OIDC_REDIRECT_URI is required in production");
  return `${origin}/api/auth/callback`;
}

export { oidc };
