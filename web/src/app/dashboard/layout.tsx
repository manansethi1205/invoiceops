import type { Metadata } from "next";
import { requirePageSession } from "@/lib/auth/require-page-session";

export const metadata: Metadata = { title: "Dashboard · InvoiceOps" };
export default async function DashboardLayout({ children }: { children: React.ReactNode }) { await requirePageSession(); return children; }
