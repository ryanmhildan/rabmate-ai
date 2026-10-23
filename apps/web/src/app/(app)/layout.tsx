import { AppShell } from "@/components/layout/AppShell";
import { AuthGate } from "@/lib/auth";

// Every page below needs the user's session, which is resolved in the browser by AuthGate
// (the API is the authority). Navigations may therefore wait for /auth/me; see DECISIONS ADR-019.
export const instant = false;

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <AuthGate>
      <AppShell>{children}</AppShell>
    </AuthGate>
  );
}
