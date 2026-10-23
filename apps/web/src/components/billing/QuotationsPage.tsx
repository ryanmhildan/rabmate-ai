"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { FileSignature } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Select } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { Pagination } from "@/components/ui/Pagination";
import { SearchInput } from "@/components/ui/SearchInput";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { SkeletonRows, Table, TableMessage, Td, Th } from "@/components/ui/Table";
import { api, errorMessage, queryString } from "@/lib/api";
import { formatMoney, formatTanggal } from "@/lib/format";
import { CLIENT_RESPONSE, DOC_STATUS, options } from "@/lib/labels";
import type { Page, QuotationListItem } from "@/lib/types";

const PAGE_SIZE = 20;
const COLUMNS = 6;

export function QuotationsPage() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const list = useQuery({
    queryKey: ["quotations", "list", { q, status, page }],
    queryFn: ({ signal }) =>
      api.get<Page<QuotationListItem>>(`/quotations${queryString({ q, status, page, page_size: PAGE_SIZE })}`, { signal }),
    placeholderData: keepPreviousData,
  });
  const items = list.data?.items ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Penawaran"
        description="Surat penawaran dari RAB yang disetujui, lengkap dengan jadwal pembayaran (termin)."
      />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput
          value={q}
          onChange={(value) => {
            setQ(value);
            setPage(1);
          }}
          placeholder="Cari nomor atau perihal…"
          label="Cari penawaran"
        />
        <Select
          aria-label="Filter status penawaran"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
          className="sm:w-48"
        >
          <option value="">Semua status</option>
          {options(DOC_STATUS).map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </div>

      {list.isSuccess && list.data.total === 0 && !q && !status ? (
        <EmptyState
          icon={FileSignature}
          title="Belum ada penawaran"
          description={
            <>
              Buat penawaran dari halaman RAB setelah versinya disetujui (kartu “Dokumen &amp; ekspor” →
              Buat penawaran). <Link href="/rab?status=approved" className="text-primary hover:underline">Lihat RAB disetujui</Link>
            </>
          }
        />
      ) : (
        <>
          <Table label="Daftar penawaran">
            <thead>
              <tr>
                <Th>Nomor</Th>
                <Th>Perihal</Th>
                <Th>Klien</Th>
                <Th className="text-right">Nilai</Th>
                <Th>Status</Th>
                <Th>Berlaku</Th>
              </tr>
            </thead>
            <tbody>
              {list.isPending && <SkeletonRows columns={COLUMNS} />}
              {list.isError && (
                <TableMessage columns={COLUMNS}>
                  <span className="text-danger">{errorMessage(list.error)}</span>{" "}
                  <Button variant="ghost" size="sm" onClick={() => void list.refetch()}>
                    Coba lagi
                  </Button>
                </TableMessage>
              )}
              {list.isSuccess && items.length === 0 && (
                <TableMessage columns={COLUMNS}>Tidak ada penawaran yang cocok dengan filter.</TableMessage>
              )}
              {items.map((x) => (
                <tr key={x.id} className="hover:bg-surface-muted/50">
                  <Td>
                    <Link href={`/penawaran/${x.id}`} className="font-mono text-xs font-medium text-primary hover:underline">
                      {x.number}
                    </Link>
                    <div className="text-xs text-muted">
                      {x.rab.number} v{x.rab_version_no}
                    </div>
                  </Td>
                  <Td>
                    {x.subject}
                    <div className="text-xs text-muted">{x.project.name}</div>
                  </Td>
                  <Td>{x.client?.name ?? "—"}</Td>
                  <Td className="text-right tabular whitespace-nowrap">{formatMoney(x.grand_total, x.currency)}</Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      <StatusBadge tone={DOC_STATUS[x.status].tone}>{DOC_STATUS[x.status].label}</StatusBadge>
                      {x.client_response && (
                        <StatusBadge tone={CLIENT_RESPONSE[x.client_response].tone}>
                          {CLIENT_RESPONSE[x.client_response].label}
                        </StatusBadge>
                      )}
                      {x.expired && <StatusBadge tone="danger">Kedaluwarsa</StatusBadge>}
                    </div>
                  </Td>
                  <Td className="text-xs whitespace-nowrap">{x.valid_until ? formatTanggal(x.valid_until) : "—"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {list.data && (
            <Pagination page={list.data.page} pageSize={list.data.page_size} total={list.data.total} onPageChange={setPage} />
          )}
        </>
      )}
    </div>
  );
}
