import type { Metadata } from "next";
import { QuotationsPage } from "@/components/billing/QuotationsPage";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export const metadata: Metadata = { title: "Penawaran" };

export default function Page() {
  return <QuotationsPage />;
}
