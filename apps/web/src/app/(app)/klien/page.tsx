import type { Metadata } from "next";
import { ClientsPage } from "@/components/clients/ClientsPage";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export const metadata: Metadata = { title: "Klien" };

export default function Page() {
  return <ClientsPage />;
}
