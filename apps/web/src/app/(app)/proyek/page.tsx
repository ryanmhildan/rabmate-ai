import type { Metadata } from "next";
import { ProjectsPage } from "@/components/projects/ProjectsPage";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export const metadata: Metadata = { title: "Proyek" };

export default function Page() {
  return <ProjectsPage />;
}
