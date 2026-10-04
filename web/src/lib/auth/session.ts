import "server-only";

import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { createClient, type RedisClientType } from "redis";

export type AppRole = "operator" | "reviewer" | "auditor" | "admin";
export type AppSession = {
  subject: string;
  roles: AppRole[];
  accessToken?: string;
  refreshToken?: string;
  expiresAt?: number;
};

export const SESSION_COOKIE = "invoiceops_session";
export const SESSION_SECONDS = 60 * 60 * 8;

export function publicOrigin(request: Request): string {
  const configured = process.env.WEB_PUBLIC_ORIGIN;
  if (configured) {
    const url = new URL(configured);
    if (process.env.WEB_ENVIRONMENT === "production" && url.protocol !== "https:") throw new Error("Production web origin must use HTTPS");
    return url.origin;
  }
  if (process.env.WEB_ENVIRONMENT === "production") throw new Error("WEB_PUBLIC_ORIGIN is required in production");
  const host = request.headers.get("host") ?? "";
  if (/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(host)) return `http://${host}`;
  return new URL(request.url).origin;
}

export function sameOriginSubmission(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (origin && origin !== "null") return origin === publicOrigin(request);
  const fetchSite = request.headers.get("sec-fetch-site");
  return fetchSite === "same-origin" || (origin === null && fetchSite === null);
}

// Local-only synthetic identities are deliberately not a production security boundary.
const DEV_SIGNING_KEY = "invoiceops-synthetic-development-session-v1";
let redisClient: RedisClientType | undefined;

export function authMode(): "development" | "oidc" {
  const mode = process.env.WEB_AUTH_MODE ?? "development";
  if (mode !== "development" && mode !== "oidc") throw new Error("Invalid WEB_AUTH_MODE");
  if (mode === "development" && process.env.WEB_ENVIRONMENT === "production") {
    throw new Error("Development authentication is forbidden in production");
  }
  return mode;
}

async function redis(): Promise<RedisClientType> {
  if (!process.env.AUTH_SESSION_REDIS_URL) throw new Error("AUTH_SESSION_REDIS_URL is required in OIDC mode");
  if (!redisClient) {
    redisClient = createClient({ url: process.env.AUTH_SESSION_REDIS_URL });
    redisClient.on("error", () => { /* Requests fail closed on Redis errors. */ });
  }
  if (!redisClient.isOpen) await redisClient.connect();
  return redisClient;
}

export function newSessionId(): string { return randomBytes(32).toString("base64url"); }

export function newDevelopmentSession(role: AppRole): string {
  if (authMode() !== "development") throw new Error("Development sessions are disabled");
  const body = Buffer.from(JSON.stringify({ role, expires: Date.now() + SESSION_SECONDS * 1000 })).toString("base64url");
  const signature = createHmac("sha256", DEV_SIGNING_KEY).update(body).digest("base64url");
  return `${body}.${signature}`;
}

function readDevelopmentSession(value: string): AppSession | null {
  const [body, signature] = value.split(".");
  if (!body || !signature || value.length > 1024) return null;
  const expected = createHmac("sha256", DEV_SIGNING_KEY).update(body).digest();
  let actual: Buffer;
  try { actual = Buffer.from(signature, "base64url"); }
  catch { return null; }
  if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) return null;
  try {
    const payload: { role: AppRole; expires: number } = JSON.parse(Buffer.from(body, "base64url").toString("utf8"));
    if (!(["operator", "reviewer", "auditor", "admin"] as string[]).includes(payload.role) || payload.expires < Date.now()) return null;
    return { subject: `synthetic-${payload.role}`, roles: [payload.role] };
  } catch { return null; }
}

export async function saveSession(id: string, session: AppSession): Promise<void> {
  if (authMode() !== "oidc") throw new Error("Only OIDC sessions are stored server-side");
  await (await redis()).set(`invoiceops:session:${id}`, JSON.stringify(session), { EX: SESSION_SECONDS });
}

export async function loadSession(id: string | undefined): Promise<AppSession | null> {
  if (!id) return null;
  if (authMode() === "oidc") {
    const raw = await (await redis()).get(`invoiceops:session:${id}`);
    return raw ? JSON.parse(raw) as AppSession : null;
  }
  return readDevelopmentSession(id);
}

export async function deleteSession(id: string | undefined): Promise<void> {
  if (!id) return;
  if (authMode() === "oidc") await (await redis()).del(`invoiceops:session:${id}`);
  // Local synthetic sessions expire quickly and are removed from the browser at logout.
}

export async function saveLoginState(state: string, verifier: string, nonce: string): Promise<void> {
  await (await redis()).set(`invoiceops:login:${state}`, JSON.stringify({ verifier, nonce }), { EX: 300, NX: true });
}

export async function consumeLoginState(state: string): Promise<{ verifier: string; nonce: string } | null> {
  const raw = await (await redis()).getDel(`invoiceops:login:${state}`);
  return raw ? JSON.parse(raw) as { verifier: string; nonce: string } : null;
}

export const sessionCookieOptions = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.WEB_ENVIRONMENT === "production",
  path: "/",
  maxAge: SESSION_SECONDS,
};
