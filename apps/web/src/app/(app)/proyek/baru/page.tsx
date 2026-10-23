import type { Metadata } from "next";
import { NewProjectPage } from "@/components/projects/NewProjectPage";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export const metadata: Metadata = { title: "Proyek baru" };

export default function Page() {
  return <NewProjectPage />;
}
