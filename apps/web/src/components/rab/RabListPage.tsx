"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Calculator, Plus } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
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
import { useCan } from "@/lib/auth";
import { formatMoney, formatTanggalWaktu } from "@/lib/format";
import { RAB_STATUS, options } from "@/lib/labels";
import type { Page, RabListItem } from "@/lib/types";
import { NewRabDialog } from "./NewRabDialog";

const PAGE_SIZE = 20;
const COLUMNS = 5;

export function RabListPage() {
  const canWrite = useCan("rab.write");
  const [q, setQ] = useState("");
  // Deep links such as /rab?status=draft (from the dashboard) preselect the filter.
  const initial = useSearchParams().get("status") ?? "";
  const [status, setStatus] = useState(initial in RAB_STATUS ? initial : "");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);

  const list = useQuery({
    queryKey: ["rab", "list", { q, status, page }],
    queryFn: ({ signal }) =>
      api.get<Page<RabListItem>>(`/rab${queryString({ q, status, page, page_size: PAGE_SIZE })}`, {
        signal,
      }),
    placeholderData: keepPreviousData,
  });

  const filtered = q !== "" || status !== "";
  const items = list.data?.items ?? [];
  const newButton = canWrite && (
    <Button onClick={() => setCreating(true)}>
      <Plus aria-hidden className="size-4" />
      RAB baru
    </Button>
  );

  return (
    <div className="space-y-5">
      <PageHeader
        title="RAB"
        description="Rencana anggaran biaya per proyek, dengan versi dan approval."
        actions={newButton}
      />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput
          value={q}
          onChange={(value) => {
            setQ(value);
            setPage(1);
          }}
          placeholder="Cari nomor, judul, proyek…"
          label="Cari RAB"
        />
        <Select
          aria-label="Filter status versi terbaru"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
            setPage(1);
          }}
          className="sm:w-48"
        >
          <option value="">Semua status</option>
          {options(RAB_STATUS).map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </div>

      {list.isSuccess && list.data.total === 0 && !filtered ? (
        <EmptyState
          icon={Calculator}
          title="Belum ada RAB"
          description="Buat RAB dari sebuah proyek: tambah item, cek harga, lalu ajukan untuk disetujui."
        >
          {newButton}
        </EmptyState>
      ) : (
        <>
          <Table label="Daftar RAB">
            <thead>
              <tr>
                <Th>RAB</Th>
                <Th>Proyek</Th>
                <Th>Versi terbaru</Th>
                <Th className="text-right">Grand total</Th>
                <Th>Diperbarui</Th>
              </tr>
            </thead>
            <tbody>
              {list.isPending && <SkeletonRows columns={COLUMNS} />}
              {list.isError && (
                <TableMessage columns={COLUMNS}>
                  <span className="text-danger">{errorMessage(list.error)}</span>
                </TableMessage>
              )}
              {list.isSuccess && items.length === 0 && (
                <TableMessage columns={COLUMNS}>Tidak ada RAB yang cocok dengan filter.</TableMessage>
              )}
              {items.map((r) => (
                <tr key={r.id} className="hover:bg-surface-muted/50">
                  <Td>
                    <Link href={`/rab/${r.id}`} className="font-medium text-primary hover:underline">
                      {r.title}
                    </Link>
                    <div className="font-mono text-xs text-muted">{r.number}</div>
                  </Td>
                  <Td>
                    <Link href={`/proyek/${r.project.id}`} className="hover:underline">
                      {r.project.name}
                    </Link>
                    <div className="text-xs text-muted">{r.project.number}</div>
                  </Td>
                  <Td>
                    <span className="mr-2 text-sm">v{r.latest_version_no}</span>
                    <StatusBadge tone={RAB_STATUS[r.latest_status].tone}>
                      {RAB_STATUS[r.latest_status].label}
                    </StatusBadge>
                  </Td>
                  <Td className="tabular text-right whitespace-nowrap">
                    {formatMoney(r.grand_total, r.currency)}
                  </Td>
                  <Td className="text-xs text-muted">{formatTanggalWaktu(r.updated_at)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {list.data && (
            <Pagination
              page={list.data.page}
              pageSize={list.data.page_size}
              total={list.data.total}
              onPageChange={setPage}
            />
          )}
        </>
      )}
      <NewRabDialog open={creating} onClose={() => setCreating(false)} />
    </div>
  );
}
