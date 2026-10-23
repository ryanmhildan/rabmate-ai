import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MeProvider } from "@/lib/auth";
import type { Me, Permission } from "@/lib/types";

function client() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
}

/** Renders with a fresh, non-retrying QueryClient so tests never share cache. */
export function renderWithQuery(ui: ReactElement) {
  return render(<QueryClientProvider client={client()}>{ui}</QueryClientProvider>);
}

export function testUser(permissions: Permission[]): Me {
  return {
    user: { id: "u1", email: "estimator@example.test", full_name: "Estimator Uji" },
    organization: { id: "o1", name: "Org Uji" },
    role: "estimator",
    role_label: "Estimator",
    permissions,
    organizations: [{ id: "o1", name: "Org Uji", role: "estimator" }],
  };
}

/** Like renderWithQuery, plus a signed-in user holding exactly `permissions`. */
export function renderAs(permissions: Permission[], ui: ReactElement) {
  return render(
    <QueryClientProvider client={client()}>
      <MeProvider me={testUser(permissions)}>{ui}</MeProvider>
    </QueryClientProvider>,
  );
}
