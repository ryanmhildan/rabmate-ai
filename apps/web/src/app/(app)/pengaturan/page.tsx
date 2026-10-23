import type { Metadata } from "next";
import { SettingsPage } from "@/components/settings/SettingsPage";

// Session-dependent page rendered behind AuthGate; see src/app/(app)/layout.tsx and ADR-019.
export const instant = false;

export const metadata: Metadata = { title: "Pengaturan" };

export default function Page() {
  return <SettingsPage />;
}
