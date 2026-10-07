import "server-only";

import { oidc, oidcConfiguration } from "./oidc";
import { authMode, loadSession, saveSession, type AppSession } from "./session";

// Coalesce refreshes in one web process. Re-read Redis inside the task so a
// request holding an older session cannot rotate an already-rotated token.
const refreshes = new Map<string, Promise<AppSession | null>>();

export async function resolveSession(id: string | undefined): Promise<AppSession | null> {
  const session = await loadSession(id);
  if (!session) return null;
  if (authMode() === "development") return session;
  if (!session.accessToken) return null;
  if ((session.expiresAt ?? 0) > Date.now() + 30_000) return session;
  if (!session.refreshToken || !id) return null;
  const pending = refreshes.get(id);
  if (pending) return pending;
  const refresh = refreshSession(id);
  refreshes.set(id, refresh);
  try {
    return await refresh;
  } finally {
    if (refreshes.get(id) === refresh) refreshes.delete(id);
  }
}

async function refreshSession(id: string): Promise<AppSession | null> {
  try {
    const session = await loadSession(id);
    if (!session?.accessToken) return null;
    if ((session.expiresAt ?? 0) > Date.now() + 30_000) return session;
    if (!session.refreshToken) return null;
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
