import type { Metadata } from "next";
import { CatalogImportPage } from "@/components/catalog/CatalogImportPage";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export const metadata: Metadata = { title: "Impor katalog harga" };

export default function Page() {
  return <CatalogImportPage />;
}
