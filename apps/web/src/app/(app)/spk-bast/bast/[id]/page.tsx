import type { Metadata } from "next";
import { Suspense } from "react";
import { FullPageMessage } from "@/components/ui/FullPageMessage";
import { BastDetail } from "@/components/workorders/BastDetail";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export const metadata: Metadata = { title: "Detail BAST" };

// The route param is read via useParams, which needs a Suspense boundary under Cache Components.
export default function Page() {
  return (
    <Suspense fallback={<FullPageMessage loading title="Memuat BAST…" />}>
      <BastDetail />
    </Suspense>
  );
}
