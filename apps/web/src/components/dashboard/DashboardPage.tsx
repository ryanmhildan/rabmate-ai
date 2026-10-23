"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Ban,
  CalendarClock,
  Check,
  FileSignature,
  Receipt,
  Building2,
  Calculator,
  ClipboardCheck,
  FileText,
  FolderKanban,
  Handshake,
  PackageCheck,
  Stamp,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { AuditItem } from "@/components/audit/AuditList";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { api, errorMessage } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { formatMoney } from "@/lib/format";
import { PROJECT_STATUS, options } from "@/lib/labels";
import type { DashboardSummary } from "@/lib/types";
import { SystemStatus } from "./SystemStatus";

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

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat
          icon={FolderKanban}
          label="Proyek"
          loading={summary.isPending}
          value={data?.projects_total.toLocaleString("id-ID")}
          href="/proyek"
        />
        <Stat
          icon={Building2}
          label="Klien aktif"
          loading={summary.isPending}
          value={data?.clients_active.toLocaleString("id-ID")}
          href="/klien"
        />
        <Stat
          icon={Wallet}
          label="Anggaran proyek terbuka"
          loading={summary.isPending}
          value={
            data && data.open_budget.length > 0
              ? data.open_budget.map((b) => formatMoney(b.total, b.currency)).join(" · ")
              : "—"
          }
          note="Prospek, berjalan, dan ditunda yang memiliki anggaran."
        />
      </div>

      {data?.rab && (
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat icon={Calculator} label="Draft RAB" loading={false} value={data.rab.draft.toLocaleString("id-ID")} href="/rab?status=draft" />
          <Stat icon={ClipboardCheck} label="RAB menunggu approval" loading={false} value={data.rab.in_review.toLocaleString("id-ID")} href="/approval" />
          <Stat
            icon={Wallet}
            label="Total estimasi disetujui"
            loading={false}
            value={
              data.rab.approved_total.length > 0
                ? data.rab.approved_total.map((t) => formatMoney(t.total, t.currency)).join(" · ")
                : "—"
            }
            note={`${data.rab.approved} RAB dengan versi disetujui.`}
          />
        </div>
      )}

      {data?.billing && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            icon={Receipt}
            label="Sisa tagihan (invoice terbit)"
            loading={false}
            value={amounts(data.billing.outstanding)}
            note={`${data.billing.outstanding.reduce((n, t) => n + t.count, 0)} invoice belum lunas.`}
            href="/invoice?payment_state=unpaid"
          />
          <Stat
            icon={AlertTriangle}
            label="Lewat jatuh tempo"
            loading={false}
            value={amounts(data.billing.overdue)}
            note={`${data.billing.overdue.reduce((n, t) => n + t.count, 0)} invoice.`}
            href="/invoice?overdue=true"
          />
          <Stat
            icon={Wallet}
            label="Diterima bulan ini"
            loading={false}
            value={amounts(data.billing.received_this_month)}
            href="/invoice?tab=pembayaran"
          />
          <Stat
            icon={CalendarClock}
            label="Termin jatuh tempo ≤ 30 hari"
            loading={false}
            value={data.billing.terms_due_soon.toLocaleString("id-ID")}
            note="Termin penawaran diterima yang belum ditagih."
            href="/penawaran"
          />
        </div>
      )}
      {data?.quotations && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Stat
            icon={FileSignature}
            label="Penawaran menunggu tanggapan klien"
            loading={false}
            value={data.quotations.awaiting_response.toLocaleString("id-ID")}
            note={`${data.quotations.draft + data.quotations.in_review} masih draft/review.`}
            href="/penawaran"
          />
          <Stat
            icon={Check}
            label="Penawaran diterima klien"
            loading={false}
            value={data.quotations.accepted.toLocaleString("id-ID")}
            href="/penawaran"
          />
        </div>
      )}
      {data?.workorders && (
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat
            icon={Handshake}
            label="Penawaran diterima tanpa SPK"
            loading={false}
            value={data.workorders.accepted_without_spk.toLocaleString("id-ID")}
            note={`${data.workorders.spk_in_review} SPK menunggu review.`}
            href="/penawaran"
          />
          <Stat
            icon={FolderKanban}
            label="SPK berjalan"
            loading={false}
            value={data.workorders.spk_open.toLocaleString("id-ID")}
            note="SPK terbit yang belum memiliki BAST akhir terbit."
            href="/spk-bast"
          />
          <Stat
            icon={PackageCheck}
            label="BAST menunggu review"
            loading={false}
            value={data.workorders.bast_in_review.toLocaleString("id-ID")}
            href="/spk-bast?tab=bast"
          />
        </div>
      )}
      {data?.documents && (
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat
            icon={Stamp}
            label="RAB siap diterbitkan"
            loading={false}
            value={data.documents.approved_rab_not_issued.toLocaleString("id-ID")}
            note="Versi disetujui yang belum memiliki dokumen terbit."
            href="/rab?status=approved"
          />
          <Stat
            icon={FileText}
            label="Dokumen terbit"
            loading={false}
            value={data.documents.issued.toLocaleString("id-ID")}
            href="/dokumen?status=issued"
          />
          <Stat
            icon={Ban}
            label="Dokumen dibatalkan"
            loading={false}
            value={data.documents.void.toLocaleString("id-ID")}
            href="/dokumen?status=void"
          />
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <Card title="Proyek per status">
            {data && data.projects_total === 0 ? (
              <p className="text-sm text-muted">
                Belum ada proyek.{" "}
                <Link href="/proyek" className="text-primary hover:underline">
                  Buat proyek pertama
                </Link>
                .
              </p>
            ) : (
              <ul className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                {options(PROJECT_STATUS).map(({ value, label }) => (
                  <li key={value} className="rounded-md bg-surface-muted px-3 py-2">
                    <p className="text-xs text-muted">{label}</p>
                    <p className="tabular text-lg font-semibold">
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

function Stat({
  icon: Icon,
  label,
  value,
  loading,
  href,
  note,
}: {
  icon: typeof Wallet;
  label: string;
  value: ReactNode;
  loading: boolean;
  href?: string;
  note?: string;
}) {
  const body = (
    <div className="h-full rounded-lg border border-border bg-surface p-4">
      <p className="flex items-center gap-2 text-sm text-muted">
        <Icon aria-hidden className="size-4" />
        {label}
      </p>
      {loading ? (
        <div className="mt-2 h-7 w-24 animate-pulse rounded bg-surface-muted" />
      ) : (
        <p
          className={`tabular mt-1 font-semibold ${
            typeof value === "string" && value.length > 14 ? "text-lg" : "text-2xl"
          }`}
        >
          {value}
        </p>
      )}
      {note && <p className="mt-1 text-xs text-muted">{note}</p>}
    </div>
  );
  return href ? (
    <Link href={href} className="block rounded-lg hover:ring-2 hover:ring-primary/20">
      {body}
    </Link>
  ) : (
    body
  );
}

function amounts(rows: { currency: string; total: string }[]): string {
  return rows.length ? rows.map((t) => formatMoney(t.total, t.currency)).join(" · ") : "—";
}
