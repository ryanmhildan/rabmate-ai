import type { Metadata } from "next";
import { Suspense } from "react";
import { ComparePage } from "@/components/rab/ComparePage";
import { FullPageMessage } from "@/components/ui/FullPageMessage";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export const metadata: Metadata = { title: "Bandingkan versi RAB" };

export default function Page() {
  return (
    <Suspense fallback={<FullPageMessage loading title="Memuat perbandingan…" />}>
      <ComparePage />
    </Suspense>
  );
}
