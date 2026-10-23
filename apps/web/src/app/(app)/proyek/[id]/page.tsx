import type { Metadata } from "next";
import { Suspense } from "react";
import { ProjectDetail } from "@/components/projects/ProjectDetail";
import { FullPageMessage } from "@/components/ui/FullPageMessage";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export const metadata: Metadata = { title: "Detail proyek" };

// Data is fetched client-side with the user's session; the route param is read via useParams,
// which needs a Suspense boundary under Cache Components.
export default function Page() {
  return (
    <Suspense fallback={<FullPageMessage loading title="Memuat proyek…" />}>
      <ProjectDetail />
    </Suspense>
  );
}
