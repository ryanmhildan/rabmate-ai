import type { Metadata } from "next";
import { Suspense } from "react";
import { DocumentsPage } from "@/components/documents/DocumentsPage";
import { FullPageMessage } from "@/components/ui/FullPageMessage";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export const metadata: Metadata = { title: "Dokumen" };

// The status filter is read from the URL (useSearchParams), which needs a Suspense boundary.
export default function Page() {
  return (
    <Suspense fallback={<FullPageMessage loading title="Memuat dokumen…" />}>
      <DocumentsPage />
    </Suspense>
  );
}
