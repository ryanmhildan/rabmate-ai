import type { Metadata } from "next";
import { Suspense } from "react";
import { RabWorkspace } from "@/components/rab/RabWorkspace";
import { FullPageMessage } from "@/components/ui/FullPageMessage";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export const metadata: Metadata = { title: "RAB" };

// useParams/useSearchParams need a Suspense boundary under Cache Components.
export default function Page() {
  return (
    <Suspense fallback={<FullPageMessage loading title="Memuat RAB…" />}>
      <RabWorkspace />
    </Suspense>
  );
}
