"use client";

import { FileCheck2, Gauge, Inbox, Menu, ScanLine, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, required } from "@/lib/api/client";

type SessionView = { subject: string; roles: string[] };

const links = [
  { href: "/dashboard", label: "Dashboard", icon: Gauge },
  { href: "/intake", label: "Invoice intake", icon: ScanLine },
  { href: "/invoices", label: "Invoices", icon: FileCheck2 },
  { href: "/reviews", label: "Review queue", icon: Inbox },
];

function breadcrumbFor(path: string): string {
  if (path === "/cases" || path.startsWith("/cases/")) return "Payable case";
  return links.find((item) => path.startsWith(item.href))?.label ?? "InvoiceOps";
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const publicPage = ["/login", "/forbidden", "/session-expired", "/provider-error"].includes(path);
  const session = useQuery<SessionView>({
    queryKey: ["auth-session"],
    queryFn: async () => {
      const response = await fetch("/api/auth/session");
      if (!response.ok) throw new Error("Session unavailable");
      return response.json() as Promise<SessionView>;
    },
    enabled: !publicPage,
    retry: false,
  });
  const dashboard = useQuery({
    queryKey: ["shell-summary"],
    queryFn: () => required(api.GET("/v1/dashboard/summary")),
    refetchInterval: 30_000,
    enabled: !publicPage && !!session.data,
  });
  const health = useQuery({
    queryKey: ["health-ready"],
    queryFn: async () => (await api.GET("/health/ready")).response.ok,
    refetchInterval: 30_000,
    enabled: !publicPage && !!session.data,
  });
  if (publicPage) return <main id="main" className="main-content"><a href="#main" className="skip-link">Skip to content</a>{children}</main>;
  const breadcrumb = breadcrumbFor(path);
  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">Skip to content</a>
      <aside className={`sidebar ${open ? "sidebar-open" : ""}`} aria-label="Primary navigation">
        <div className="brand"><span className="brand-mark">IO</span><div><strong>InvoiceOps</strong><small>AP control plane</small></div></div>
        <nav aria-label="Primary navigation">
          {links.filter(({ href }) =>
            href === "/reviews" ? session.data?.roles.some((role) => ["reviewer", "auditor", "admin"].includes(role))
              : href === "/intake" ? session.data?.roles.some((role) => ["operator", "reviewer", "admin"].includes(role)) : true
          ).map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} className={path.startsWith(href) ? "nav-link active" : "nav-link"} onClick={() => setOpen(false)}>
              <Icon size={18} aria-hidden="true" />{label}
              {href === "/reviews" && dashboard.data?.reviews_waiting ? (
                <span className="nav-count" aria-label={`${dashboard.data.reviews_waiting} pending reviews`}>
                  {dashboard.data.reviews_waiting}
                </span>
              ) : null}
            </Link>
          ))}
        </nav>
        <div className="shell-status" aria-live="polite">
          <span className={`health-dot ${health.data ? "healthy" : "unhealthy"}`} aria-hidden="true" />
          API {health.data ? "ready" : "unavailable"}
        </div>
        <div className="boundary-note"><strong>{session.data?.subject ?? "Session"}</strong><span>{session.data?.roles.join(", ") ?? "Checking identity"}</span><form action="/api/auth/logout" method="post"><button type="submit" className="button button-secondary">Sign out</button></form></div>
      </aside>
      <div className="content-shell">
        <header className="topbar"><button className="icon-button mobile-only" onClick={() => setOpen(!open)} aria-label={open ? "Close navigation" : "Open navigation"}>{open ? <X /> : <Menu />}</button><span>InvoiceOps / <strong>{breadcrumb}</strong></span><span className="environment">LOCAL</span></header>
        <main id="main" className="main-content">{children}</main>
      </div>
    </div>
  );
}
