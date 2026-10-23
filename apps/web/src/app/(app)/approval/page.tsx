import type { Metadata } from "next";
import { ApprovalQueuePage } from "@/components/approvals/ApprovalQueuePage";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export const metadata: Metadata = { title: "Approval" };

export default function Page() {
  return <ApprovalQueuePage />;
}
