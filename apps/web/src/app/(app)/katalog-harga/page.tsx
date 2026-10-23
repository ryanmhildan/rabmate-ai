import type { Metadata } from "next";
import { CatalogPage } from "@/components/catalog/CatalogPage";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export const metadata: Metadata = { title: "Katalog Harga" };

export default function Page() {
  return <CatalogPage />;
}
