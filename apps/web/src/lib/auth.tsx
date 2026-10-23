"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { FullPageMessage } from "@/components/ui/FullPageMessage";
import { ApiError, UNAUTHENTICATED_EVENT, api, errorMessage } from "./api";
import type { Me, Permission } from "./types";

export const ME_QUERY_KEY = ["me"] as const;

const MeContext = createContext<Me | null>(null);

/** Supplies a known user (AuthGate does this after /auth/me); used to render components in tests. */
export function MeProvider({ me, children }: { me: Me; children: ReactNode }) {
  return <MeContext.Provider value={me}>{children}</MeContext.Provider>;
}

/** Only same-site relative paths are accepted as post-login targets (no open redirects). */
export function safeNextPath(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) {
    return "/";
  }
  return value;
}

export function loginUrl(pathname: string): string {
  return pathname && pathname !== "/" ? `/login?next=${encodeURIComponent(pathname)}` : "/login";
}

/**
 * Loads the current user for every authenticated page. A 401 (no/expired session) sends the
 * browser to /login; permissions shown in the UI are a convenience — the API enforces them.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: ({ signal }) => api.get<Me>("/auth/me", { signal }),
    retry: false,
    staleTime: 5 * 60_000,
  });

  const unauthenticated = me.error instanceof ApiError && me.error.status === 401;

  useEffect(() => {
    // window.location (not usePathname) keeps this layout prerenderable for dynamic routes.
    if (unauthenticated) router.replace(loginUrl(window.location.pathname));
  }, [unauthenticated, router]);

  useEffect(() => {
    // Any API call that finds the session gone (expired, revoked, role changed) lands here.
    const onUnauthenticated = () => {
      queryClient.clear();
      router.replace(loginUrl(window.location.pathname));
    };
    window.addEventListener(UNAUTHENTICATED_EVENT, onUnauthenticated);
    return () => window.removeEventListener(UNAUTHENTICATED_EVENT, onUnauthenticated);
  }, [queryClient, router]);

  if (me.data) return <MeContext.Provider value={me.data}>{children}</MeContext.Provider>;
  if (me.isPending || unauthenticated) return <FullPageMessage loading title="Memuat sesi…" />;
  return (
    <FullPageMessage
      title="Tidak dapat memuat sesi"
      description={errorMessage(me.error)}
      action={{ label: "Coba lagi", onClick: () => void me.refetch() }}
    />
  );
}

export function useMe(): Me {
  const me = useContext(MeContext);
  if (!me) throw new Error("useMe must be used inside <AuthGate>");
  return me;
}

export function useCan(permission: Permission): boolean {
  return useMe().permissions.includes(permission);
}

export function useLogout() {
  const router = useRouter();
  const queryClient = useQueryClient();
  return async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      queryClient.clear();
      router.replace("/login");
    }
  };
}
