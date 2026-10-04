import { authMode } from "@/lib/auth/session";

export const dynamic = "force-dynamic";

export default function LoginPage() {
  const development = authMode() === "development";
  return <section className="card stack" aria-labelledby="login-heading"><h1 id="login-heading">Sign in to InvoiceOps</h1><p>Access to payable cases and review history requires a session.</p>{development ? <form action="/api/auth/dev-login" method="post" className="stack"><label htmlFor="role">Synthetic local identity</label><select name="role" id="role" defaultValue="reviewer"><option value="operator">Operator</option><option value="reviewer">Reviewer</option><option value="auditor">Auditor</option><option value="admin">Admin</option></select><button className="button button-primary" type="submit">Sign in locally</button><p className="help-text">Development identities are unverified and must not be used in production.</p></form> : <a className="button button-primary" href="/api/auth/login">Sign in with identity provider</a>}</section>;
}
