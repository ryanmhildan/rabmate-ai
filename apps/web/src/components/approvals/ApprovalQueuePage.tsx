"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import { ClipboardCheck } from "lucide-react";
import Link from "next/link";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { SkeletonRows, Table, TableMessage, Td, Th } from "@/components/ui/Table";
import { api, errorMessage, queryString } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { formatMoney, formatTanggalWaktu } from "@/lib/format";
import type {
  BastListItem,
  InvoiceListItem,
  Page,
  PendingApproval,
  QuotationListItem,
  SpkListItem,
} from "@/lib/types";

export function ApprovalQueuePage() {
  const canApproveRab = useCan("rab.approve");
  const canApproveDocs = useCan("documents.approve");

  if (!canApproveRab && !canApproveDocs) {
    return (
      <div className="space-y-5">
        <PageHeader title="Approval" />
        <EmptyState
          icon={ClipboardCheck}
          title="Tidak ada akses approval"
          description="Role Anda tidak memiliki izin menyetujui RAB atau dokumen. Pengajuan Anda dapat dipantau dari halaman masing-masing."
        />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <PageHeader title="Approval" description="Pengajuan yang menunggu keputusan Anda." />
      {canApproveRab && <RabQueue />}
      {canApproveDocs && <DocumentQueue />}
    </div>
  );
}

function RabQueue() {
  const queue = useQuery({
    queryKey: ["approvals", "pending"],
    queryFn: ({ signal }) => api.get<PendingApproval[]>("/approvals/pending", { signal }),
  });
  return (
    <Card title="RAB">
      {queue.isSuccess && queue.data.length === 0 ? (
        <p className="text-sm text-muted">Tidak ada RAB yang menunggu persetujuan.</p>
      ) : (
        <Table label="Antrian approval RAB">
          <thead>
            <tr>
              <Th>RAB</Th>
              <Th>Proyek</Th>
              <Th>Diajukan</Th>
              <Th className="text-right">Grand total</Th>
            </tr>
          </thead>
          <tbody>
            {queue.isPending && <SkeletonRows columns={4} rows={3} />}
            {queue.isError && (
              <TableMessage columns={4}>
                <span className="text-danger">{errorMessage(queue.error)}</span>
              </TableMessage>
            )}
            {queue.data?.map((entry) => (
              <tr key={`${entry.rab_id}-${entry.version_no}`} className="hover:bg-surface-muted/50">
                <Td>
                  <Link
                    href={`/rab/${entry.rab_id}?v=${entry.version_no}`}
                    className="font-medium text-primary hover:underline"
                  >
                    {entry.title}
                  </Link>
                  <div className="font-mono text-xs text-muted">
                    {entry.number} · v{entry.version_no}
                  </div>
                </Td>
                <Td>{entry.project.name}</Td>
                <Td className="text-xs">
                  {entry.submitted_by?.full_name ?? "-"}
                  {entry.submitted_at && (
                    <div className="text-muted">{formatTanggalWaktu(entry.submitted_at)}</div>
                  )}
                </Td>
                <Td className="tabular text-right">{formatMoney(entry.grand_total, entry.currency)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

type QueueRow = {
  key: string;
  type: string;
  href: string;
  number: string | null;
  title: string;
  project: string;
  value: string | null;
};

const IN_REVIEW = queryString({ status: "in_review", page_size: 100 });

async function inReview<T>(path: string, signal: AbortSignal): Promise<T[]> {
  return (await api.get<Page<T>>(`${path}${IN_REVIEW}`, { signal })).items;
}

const SOURCES: { path: string; load: (signal: AbortSignal) => Promise<QueueRow[]> }[] = [
  {
    path: "/quotations",
    load: async (signal) =>
      (await inReview<QuotationListItem>("/quotations", signal)).map((x) => ({
        key: `q-${x.id}`,
        type: "Penawaran",
        href: `/penawaran/${x.id}`,
        number: x.number,
        title: x.subject,
        project: x.project.name,
        value: formatMoney(x.grand_total, x.currency),
      })),
  },
  {
    path: "/invoices",
    load: async (signal) =>
      (await inReview<InvoiceListItem>("/invoices", signal)).map((x) => ({
        key: `i-${x.id}`,
        type: "Invoice",
        href: `/invoice/${x.id}`,
        number: x.number,
        title: x.title,
        project: x.project.name,
        value: formatMoney(x.grand_total, x.currency),
      })),
  },
  {
    path: "/spk",
    load: async (signal) =>
      (await inReview<SpkListItem>("/spk", signal)).map((x) => ({
        key: `s-${x.id}`,
        type: "SPK",
        href: `/spk-bast/spk/${x.id}`,
        number: x.number,
        title: x.title,
        project: x.project.name,
        value: formatMoney(x.contract_value, x.currency),
      })),
  },
  {
    path: "/bast",
    load: async (signal) =>
      (await inReview<BastListItem>("/bast", signal)).map((x) => ({
        key: `b-${x.id}`,
        type: "BAST",
        href: `/spk-bast/bast/${x.id}`,
        number: x.number,
        title: x.title,
        project: x.project.name,
        value: null,
      })),
  },
];

function DocumentQueue() {
  const results = useQueries({
    queries: SOURCES.map((source) => ({
      queryKey: ["approvals", "documents", source.path],
      queryFn: ({ signal }: { signal: AbortSignal }) => source.load(signal),
    })),
  });
  const pending = results.some((r) => r.isPending);
  const failed = results.find((r) => r.isError);
  const rows = results.flatMap((r) => r.data ?? []);

  return (
    <Card title="Dokumen (penawaran, invoice, SPK, BAST)">
      {!pending && !failed && rows.length === 0 ? (
        <p className="text-sm text-muted">Tidak ada dokumen yang menunggu persetujuan.</p>
      ) : (
        <Table label="Antrian approval dokumen">
          <thead>
            <tr>
              <Th>Dokumen</Th>
              <Th>Jenis</Th>
              <Th>Proyek</Th>
              <Th className="text-right">Nilai</Th>
            </tr>
          </thead>
          <tbody>
            {pending && <SkeletonRows columns={4} rows={2} />}
            {failed && (
              <TableMessage columns={4}>
                <span className="text-danger">{errorMessage(failed.error)}</span>
              </TableMessage>
            )}
            {rows.map((row) => (
              <tr key={row.key} className="hover:bg-surface-muted/50">
                <Td>
                  <Link href={row.href} className="font-medium text-primary hover:underline">
                    {row.title}
                  </Link>
                  <div className="font-mono text-xs text-muted">{row.number ?? "Belum bernomor"}</div>
                </Td>
                <Td className="text-xs">{row.type}</Td>
                <Td>{row.project}</Td>
                <Td className="tabular text-right">{row.value ?? "-"}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}
