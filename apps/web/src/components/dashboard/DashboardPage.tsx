"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { AuditItem } from "@/components/audit/AuditList";
import { Card } from "@/components/ui/Card";
import { HIGHLIGHT } from "@/components/ui/KeyFigure";
import { PageHeader } from "@/components/ui/PageHeader";
import { api, errorMessage } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { formatMoney } from "@/lib/format";
import { PROJECT_STATUS, options } from "@/lib/labels";
import type { DashboardSummary } from "@/lib/types";
import { SystemStatus } from "./SystemStatus";

type Amounts = { currency: string; total: string; count?: number }[];

type Action = { label: string; count: number; href: string; detail?: string; urgent?: boolean };

type Figure = { label: string; value: string; href?: string; note?: string };

/**
 * The dashboard answers "what is waiting on me?" first, then "where does the money stand?".
 * Plain counts sit below as a reference strip. Sections the role cannot see come back as null.
 */
export function DashboardPage() {
  const me = useMe();
  const summary = useQuery({
    queryKey: ["dashboard"],
    queryFn: ({ signal }) => api.get<DashboardSummary>("/dashboard/summary", { signal }),
    staleTime: 0, // always fresh when returning from other pages
  });
  const data = summary.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description={`Ringkasan ${me.organization.name}. Semua angka berasal dari database.`}
      />

      {summary.isError && (
        <p role="alert" className="text-sm text-danger">
          Ringkasan gagal dimuat: {errorMessage(summary.error)}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <ActionList actions={data ? actionsFrom(data) : null} />
        <MoneyPanel data={data} loading={summary.isPending} />
      </div>

      <Overview figures={data ? overviewFrom(data) : null} />

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <Card title="Proyek per status">
            {data && data.projects_total === 0 ? (
              <p className="text-sm text-muted">
                Belum ada proyek.{" "}
                <Link href="/proyek" className="font-medium text-primary underline-offset-2 hover:underline">
                  Buat proyek pertama
                </Link>
                .
              </p>
            ) : (
              <ul className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                {options(PROJECT_STATUS).map(({ value, label }) => (
                  <li key={value} className="rounded-md bg-surface-muted px-3 py-2">
                    <p className="text-xs text-muted">{label}</p>
                    <p className="tabular text-lg font-bold">
                      {summary.isPending ? "…" : (data?.projects_by_status[value] ?? 0)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Aktivitas terakhir">
            {data?.recent_activity === null ? (
              <p className="text-sm text-muted">Role Anda tidak memiliki akses ke log aktivitas.</p>
            ) : data && data.recent_activity.length === 0 ? (
              <p className="text-sm text-muted">Belum ada aktivitas.</p>
            ) : (
              <ul>{data?.recent_activity?.map((entry) => <AuditItem key={entry.id} entry={entry} />)}</ul>
            )}
          </Card>
        </div>
        <SystemStatus />
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- what needs action

/** Queues in the order they cost money or block someone, overdue invoices first. */
export function actionsFrom(data: DashboardSummary): Action[] {
  const actions: Action[] = [];
  if (data.billing) {
    actions.push({
      label: "Invoice lewat jatuh tempo",
      count: countOf(data.billing.overdue),
      detail: amounts(data.billing.overdue),
      href: "/invoice?overdue=true",
      urgent: true,
    });
    actions.push({
      label: "Termin jatuh tempo dalam 30 hari",
      count: data.billing.terms_due_soon,
      detail: "Termin penawaran diterima yang belum ditagih.",
      href: "/penawaran",
    });
  }
  if (data.rab) {
    actions.push({ label: "RAB menunggu approval", count: data.rab.in_review, href: "/approval" });
  }
  if (data.documents) {
    actions.push({
      label: "RAB disetujui, belum diterbitkan",
      count: data.documents.approved_rab_not_issued,
      href: "/rab?status=approved",
    });
  }
  if (data.workorders) {
    actions.push({
      label: "Penawaran diterima tanpa SPK",
      count: data.workorders.accepted_without_spk,
      href: "/penawaran",
    });
    actions.push({ label: "SPK menunggu review", count: data.workorders.spk_in_review, href: "/spk-bast" });
    actions.push({ label: "BAST menunggu review", count: data.workorders.bast_in_review, href: "/spk-bast?tab=bast" });
  }
  if (data.quotations) {
    actions.push({
      label: "Penawaran menunggu tanggapan klien",
      count: data.quotations.awaiting_response,
      href: "/penawaran",
    });
  }
  return actions.filter((action) => action.count > 0);
}

function ActionList({ actions }: { actions: Action[] | null }) {
  return (
    <section aria-labelledby="dashboard-actions" className="flex flex-col rounded-lg border border-border bg-surface">
      <header className="border-b border-border px-4 py-3">
        <h2 id="dashboard-actions" className="text-[15px] font-semibold">
          Perlu tindakan
        </h2>
      </header>
      {actions === null ? (
        <div aria-hidden className="space-y-3 p-4">
          {[0, 1, 2].map((row) => (
            <div key={row} className="h-8 animate-pulse rounded bg-surface-muted" />
          ))}
        </div>
      ) : actions.length === 0 ? (
        <p className="grid flex-1 place-items-center px-4 py-8 text-center text-sm text-muted">
          Tidak ada antrean yang menunggu Anda.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {actions.map((action) => (
            <li key={action.label}>
              <Link
                href={action.href}
                className="flex min-h-14 items-center gap-4 px-4 py-2.5 transition-colors hover:bg-surface-muted focus-visible:-outline-offset-2"
              >
                <span
                  className={`tabular w-10 shrink-0 text-right text-2xl font-bold ${action.urgent ? "text-danger" : ""}`}
                >
                  {action.count.toLocaleString("id-ID")}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-medium">{action.label}</span>
                  {action.detail && <span className="block text-xs text-muted">{action.detail}</span>}
                </span>
                <ChevronRight aria-hidden className="size-4 shrink-0 text-muted" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- money

function MoneyPanel({ data, loading }: { data: DashboardSummary | undefined; loading: boolean }) {
  const billing = data?.billing;
  const rows: Figure[] = [];
  if (billing) {
    rows.push({ label: "Diterima bulan ini", value: amounts(billing.received_this_month), href: "/invoice?tab=pembayaran" });
    rows.push({ label: "Lewat jatuh tempo", value: amounts(billing.overdue), href: "/invoice?overdue=true" });
  }
  if (data?.rab) {
    rows.push({
      label: "Total estimasi disetujui",
      value: amounts(data.rab.approved_total),
      note: `${data.rab.approved} RAB dengan versi disetujui.`,
    });
  }
  if (data) {
    rows.push({
      label: "Anggaran proyek terbuka",
      value: amounts(data.open_budget),
      note: "Prospek, berjalan, dan ditunda yang memiliki anggaran.",
    });
  }

  return (
    <section aria-labelledby="dashboard-money" className="rounded-lg border border-border bg-surface">
      <header className="border-b border-border px-4 py-3">
        <h2 id="dashboard-money" className="text-[15px] font-semibold">
          Keuangan
        </h2>
      </header>
      {loading ? (
        <div aria-hidden className="space-y-3 p-4">
          <div className="h-10 w-48 animate-pulse rounded bg-surface-muted" />
          <div className="h-5 animate-pulse rounded bg-surface-muted" />
          <div className="h-5 animate-pulse rounded bg-surface-muted" />
        </div>
      ) : (
        <>
          {/* The single stabilo figure on this screen (DESIGN.md). */}
          {billing && (
            <Link
              href="/invoice?payment_state=unpaid"
              className="block border-b border-border px-4 py-4 transition-colors hover:bg-surface-muted focus-visible:-outline-offset-2"
            >
              <span className="block text-sm text-muted">Sisa tagihan invoice terbit</span>
              <span className="mt-1.5 block text-2xl leading-snug sm:text-3xl">
                <mark className={HIGHLIGHT}>{amounts(billing.outstanding)}</mark>
              </span>
              <span className="mt-1.5 block text-xs text-muted">
                {countOf(billing.outstanding).toLocaleString("id-ID")} invoice belum lunas.
              </span>
            </Link>
          )}
          <dl className="divide-y divide-border text-sm">
            {rows.map((row) => (
              <div
                key={row.label}
                className="relative flex min-h-11 flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 px-4 py-2.5 has-[a:hover]:bg-surface-muted"
              >
                <dt className="text-muted">
                  {row.href ? (
                    // The link's ::after covers the whole row, so the row is the tap target.
                    <Link
                      href={row.href}
                      className="underline-offset-2 after:absolute after:inset-0 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:after:outline-2 focus-visible:after:-outline-offset-2 focus-visible:after:outline-primary"
                    >
                      {row.label}
                    </Link>
                  ) : (
                    row.label
                  )}
                </dt>
                <dd className="tabular font-semibold">{row.value}</dd>
                {row.note && <dd className="w-full text-xs text-muted">{row.note}</dd>}
              </div>
            ))}
          </dl>
        </>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- reference counts

function overviewFrom(data: DashboardSummary): Figure[] {
  const figures: Figure[] = [
    { label: "Proyek", value: count(data.projects_total), href: "/proyek" },
    { label: "Klien aktif", value: count(data.clients_active), href: "/klien" },
  ];
  if (data.rab) figures.push({ label: "Draft RAB", value: count(data.rab.draft), href: "/rab?status=draft" });
  if (data.quotations) {
    figures.push({ label: "Penawaran diterima", value: count(data.quotations.accepted), href: "/penawaran" });
  }
  if (data.workorders) figures.push({ label: "SPK berjalan", value: count(data.workorders.spk_open), href: "/spk-bast" });
  if (data.documents) {
    figures.push({ label: "Dokumen terbit", value: count(data.documents.issued), href: "/dokumen?status=issued" });
    figures.push({ label: "Dokumen dibatalkan", value: count(data.documents.void), href: "/dokumen?status=void" });
  }
  return figures;
}

function Overview({ figures }: { figures: Figure[] | null }) {
  return (
    // Each cell draws its right and bottom edge; the -1px margins push the outermost edges under the
    // clipped frame, so a short last row leaves plain surface instead of a grey block.
    <section aria-label="Jumlah data" className="overflow-hidden rounded-lg border border-border bg-surface">
      <ul className="-mr-px -mb-px grid grid-cols-2 sm:grid-cols-4 xl:grid-flow-col xl:grid-cols-none xl:auto-cols-fr">
        {(figures ?? PLACEHOLDER_FIGURES).map((figure) => {
          const body = (
            <>
              <span className="block text-xs text-muted">{figure.label}</span>
              <span className="tabular mt-0.5 block text-xl font-bold">{figure.value}</span>
            </>
          );
          return (
            <li key={figure.label} className="border-r border-b border-border">
              {figure.href ? (
                <Link
                  href={figure.href}
                  className="block h-full px-4 py-3 transition-colors hover:bg-surface-muted focus-visible:-outline-offset-2"
                >
                  {body}
                </Link>
              ) : (
                <div className="h-full px-4 py-3">{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const PLACEHOLDER_FIGURES: Figure[] = ["Proyek", "Klien aktif", "Draft RAB", "Penawaran diterima"].map((label) => ({
  label,
  value: "…",
}));

// --------------------------------------------------------------------------- helpers

function count(value: number): string {
  return value.toLocaleString("id-ID");
}

function countOf(rows: Amounts): number {
  return rows.reduce((n, row) => n + (row.count ?? 0), 0);
}

/** No rows means nothing in that bucket, which reads clearer as "Rp 0" than as a dash. */
function amounts(rows: Amounts): string {
  return rows.length ? rows.map((t) => formatMoney(t.total, t.currency)).join(" · ") : formatMoney("0", "IDR");
}
