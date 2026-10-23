import type { Metadata } from "next";
import { Suspense } from "react";
import { FullPageMessage } from "@/components/ui/FullPageMessage";
import { SpkDetail } from "@/components/workorders/SpkDetail";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export const metadata: Metadata = { title: "Detail SPK" };

// The route param is read via useParams, which needs a Suspense boundary under Cache Components.
export default function Page() {
  return (
    <Suspense fallback={<FullPageMessage loading title="Memuat SPK…" />}>
      <SpkDetail />
    </Suspense>
  );
}
