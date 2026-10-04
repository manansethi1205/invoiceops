import type { Metadata } from "next";
import { requirePageSession } from "@/lib/auth/require-page-session";

export const metadata: Metadata = { title: "Review queue · InvoiceOps" };
export default async function ReviewsLayout({ children }: { children: React.ReactNode }) { await requirePageSession(["reviewer", "auditor", "admin"]); return children; }
