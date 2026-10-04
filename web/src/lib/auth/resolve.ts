import "server-only";

import { oidc, oidcConfiguration } from "./oidc";
import { authMode, loadSession, saveSession, type AppSession } from "./session";

export async function resolveSession(id: string | undefined): Promise<AppSession | null> {
  const session = await loadSession(id);
  if (!session) return null;
  if (authMode() === "development") return session;
  if (!session.accessToken) return null;
  if ((session.expiresAt ?? 0) > Date.now() + 30_000) return session;
  if (!session.refreshToken || !id) return null;
  try {
    const tokens = await oidc.refreshTokenGrant(await oidcConfiguration(), session.refreshToken);
    const refreshed: AppSession = {
      ...session,
      accessToken: tokens.access_token,
      refreshToken: tokens.refresh_token ?? session.refreshToken,
      expiresAt: Date.now() + (tokens.expires_in ?? 300) * 1000,
    };
    await saveSession(id, refreshed);
    return refreshed;
  } catch {
    // Never forward an expired token if renewal fails.
    return null;
  }
}
