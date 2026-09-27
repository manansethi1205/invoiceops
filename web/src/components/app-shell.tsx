"use client";

import { FileCheck2, Gauge, Inbox, Menu, ScanLine, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, required } from "@/lib/api/client";

const links = [
  { href: "/dashboard", label: "Dashboard", icon: Gauge },
  { href: "/intake", label: "Invoice intake", icon: ScanLine },
  { href: "/invoices", label: "Invoices", icon: FileCheck2 },
  { href: "/reviews", label: "Review queue", icon: Inbox },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const dashboard = useQuery({
    queryKey: ["shell-summary"],
    queryFn: () => required(api.GET("/v1/dashboard/summary")),
    refetchInterval: 30_000,
  });
  const health = useQuery({
    queryKey: ["health-ready"],
    queryFn: async () => (await api.GET("/health/ready")).response.ok,
    refetchInterval: 30_000,
  });
  const breadcrumb = links.find((item) => path.startsWith(item.href))?.label ?? "InvoiceOps";
  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">Skip to content</a>
      <aside className={`sidebar ${open ? "sidebar-open" : ""}`} aria-label="Primary navigation">
        <div className="brand"><span className="brand-mark">IO</span><div><strong>InvoiceOps</strong><small>AP control plane</small></div></div>
        <nav aria-label="Primary navigation">
          {links.map(({ href, label, icon: Icon }) => (
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
        <div className="boundary-note"><strong>Development identity</strong><span>Reviewer headers are unverified. Do not use as production authentication.</span></div>
      </aside>
      <div className="content-shell">
        <header className="topbar"><button className="icon-button mobile-only" onClick={() => setOpen(!open)} aria-label={open ? "Close navigation" : "Open navigation"}>{open ? <X /> : <Menu />}</button><span>InvoiceOps / <strong>{breadcrumb}</strong></span><span className="environment">LOCAL</span></header>
        <main id="main" className="main-content">{children}</main>
      </div>
    </div>
  );
}
