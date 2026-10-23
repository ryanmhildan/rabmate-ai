import type { Metadata } from "next";
import { Suspense } from "react";
import { RabImportPage } from "@/components/rab/RabImportPage";
import { FullPageMessage } from "@/components/ui/FullPageMessage";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export const metadata: Metadata = { title: "Impor item RAB" };

// Reads the route param and ?versi= (useParams/useSearchParams): needs a Suspense boundary.
export default function Page() {
  return (
    <Suspense fallback={<FullPageMessage loading title="Memuat…" />}>
      <RabImportPage />
    </Suspense>
  );
}
