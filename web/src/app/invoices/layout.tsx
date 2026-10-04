import type { Metadata } from "next";
import { requirePageSession } from "@/lib/auth/require-page-session";

export const metadata: Metadata = { title: "Invoices · InvoiceOps" };
export default async function InvoicesLayout({ children }: { children: React.ReactNode }) { await requirePageSession(); return children; }
