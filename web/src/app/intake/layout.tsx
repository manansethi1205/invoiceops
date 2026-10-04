import type { Metadata } from "next";
import { requirePageSession } from "@/lib/auth/require-page-session";

export const metadata: Metadata = { title: "Invoice intake · InvoiceOps" };
export default async function IntakeLayout({ children }: { children: React.ReactNode }) { await requirePageSession(["operator", "reviewer", "admin"]); return children; }
