"use client";

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Bot, Database, RefreshCw, Server } from "lucide-react";
import { ApiError, getHealth, type ComponentStatus } from "@/lib/api";
import { formatTanggalWaktu } from "@/lib/format";
import { StatusBadge, type BadgeTone } from "@/components/ui/StatusBadge";

const COMPONENT_LABEL: Record<ComponentStatus, { tone: BadgeTone; text: string }> = {
  ok: { tone: "success", text: "Terhubung" },
  error: { tone: "danger", text: "Gagal" },
  disabled: { tone: "neutral", text: "Belum dikonfigurasi" },
};

export function SystemStatus() {
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => getHealth(signal),
    // A status panel should show the failure immediately rather than retrying silently.
    retry: false,
    staleTime: 0,
  });

  return (
    <section
      aria-labelledby="system-status-title"
      className="rounded-lg border border-border bg-surface"
    >
      <header className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 id="system-status-title" className="text-sm font-semibold">
          Status sistem
        </h2>
        <button
          type="button"
          onClick={() => void refetch()}
          disabled={isFetching}
          className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1 text-xs text-muted hover:bg-surface-muted disabled:opacity-50"
        >
          <RefreshCw aria-hidden className={`size-3.5 ${isFetching ? "animate-spin" : ""}`} />
          Periksa ulang
        </button>
      </header>

      {isPending && !error && (
        <div role="status" aria-live="polite" className="space-y-3 p-4">
          <span className="sr-only">Memeriksa status…</span>
          {[0, 1, 2].map((row) => (
            <div key={row} className="h-5 animate-pulse rounded bg-surface-muted" />
          ))}
        </div>
      )}

      {error && !data && (
        <div role="alert" className="p-4 text-sm">
          <p className="font-medium text-danger">API tidak dapat dihubungi</p>
          <p className="mt-1 text-muted">
            {error instanceof ApiError ? error.message : "Terjadi kesalahan tak terduga."}
          </p>
        </div>
      )}

      {data && (
        <dl className="divide-y divide-border text-sm">
          <Row icon={Server} label="API">
            <StatusBadge tone={data.status === "ok" ? "success" : "warning"}>
              {data.status === "ok" ? "Normal" : "Terganggu"}
            </StatusBadge>
          </Row>
          <Row icon={Database} label="Database">
            <StatusBadge tone={COMPONENT_LABEL[data.database].tone}>
              {COMPONENT_LABEL[data.database].text}
            </StatusBadge>
          </Row>
          <Row icon={Bot} label="AI lokal (Hermes)">
            <StatusBadge tone={COMPONENT_LABEL[data.ai].tone}>
              {data.ai === "error" ? "Tidak tersedia" : COMPONENT_LABEL[data.ai].text}
            </StatusBadge>
          </Row>
          <p className="px-4 py-2 text-xs text-muted">
            Versi {data.version} · {data.environment} · diperiksa {formatTanggalWaktu(data.time)}
          </p>
        </dl>
      )}
    </section>
  );
}

function Row({
  icon: Icon,
  label,
  children,
}: {
  icon: typeof Server;
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-2.5">
      <dt className="flex items-center gap-2 text-muted">
        <Icon aria-hidden className="size-4" />
        {label}
      </dt>
      <dd>{children}</dd>
    </div>
  );
}
