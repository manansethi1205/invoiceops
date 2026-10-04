import { requirePageSession } from "@/lib/auth/require-page-session";

export default async function CasesLayout({ children }: { children: React.ReactNode }) {
  await requirePageSession();
  return children;
}
