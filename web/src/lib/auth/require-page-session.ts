import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { resolveSession } from "./resolve";
import { SESSION_COOKIE, type AppRole, type AppSession } from "./session";

export async function requirePageSession(roles?: readonly AppRole[]): Promise<AppSession> {
  const id = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!id) redirect("/login");
  let session: AppSession | null;
  try { session = await resolveSession(id); }
  catch { redirect("/provider-error"); }
  if (!session) redirect("/session-expired");
  if (roles && !session.roles.some((role) => roles.includes(role))) redirect("/forbidden");
  return session;
}
