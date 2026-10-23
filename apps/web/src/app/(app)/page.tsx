import { DashboardPage } from "@/components/dashboard/DashboardPage";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export default function Page() {
  return <DashboardPage />;
}
