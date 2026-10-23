"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { FolderKanban, Plus } from "lucide-react";
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
import { useCan } from "@/lib/auth";
import { formatMoney, formatTanggal } from "@/lib/format";
import { PROJECT_STATUS, PROJECT_TYPE, options } from "@/lib/labels";
import type { Page, ProjectListItem } from "@/lib/types";

const PAGE_SIZE = 20;
const COLUMNS = 6;

export function ProjectsPage() {
  const canWrite = useCan("projects.write");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);

  const list = useQuery({
    queryKey: ["projects", { q, status, type, page }],
    queryFn: ({ signal }) =>
      api.get<Page<ProjectListItem>>(
        `/projects${queryString({ q, status, project_type: type, page, page_size: PAGE_SIZE })}`,
        { signal },
      ),
    placeholderData: keepPreviousData,
  });

  const filtered = q !== "" || status !== "" || type !== "";
  const items = list.data?.items ?? [];
  const newButton = canWrite && (
    <Link
      href="/proyek/baru"
      className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3.5 text-sm font-medium text-primary-foreground hover:opacity-90"
    >
      <Plus aria-hidden className="size-4" />
      Proyek baru
    </Link>
  );

  return (
    <div className="space-y-5">
      <PageHeader
        title="Proyek"
        description="Semua jenis proyek: konstruksi, fabrikasi, pengadaan, IT, jasa, dan lainnya."
        actions={newButton}
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
        <SearchInput
          value={q}
          onChange={(value) => {
            setQ(value);
            setPage(1);
          }}
          placeholder="Cari nomor, nama, lokasi, klien…"
          label="Cari proyek"
        />
        <Select
          aria-label="Filter status"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value);
            setPage(1);
          }}
          className="sm:w-40"
        >
          <option value="">Semua status</option>
          {options(PROJECT_STATUS).map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Filter jenis"
          value={type}
          onChange={(event) => {
            setType(event.target.value);
            setPage(1);
          }}
          className="sm:w-52"
        >
          <option value="">Semua jenis</option>
          {options(PROJECT_TYPE).map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </div>

      {list.isSuccess && list.data.total === 0 && !filtered ? (
        <EmptyState
          icon={FolderKanban}
          title="Belum ada proyek"
          description="Proyek adalah wadah untuk RAB, penawaran, invoice, SPK, dan BAST."
        >
          {newButton}
        </EmptyState>
      ) : (
        <>
          <Table label="Daftar proyek">
            <thead>
              <tr>
                <Th>Proyek</Th>
                <Th>Klien</Th>
                <Th>Jenis</Th>
                <Th>Jadwal</Th>
                <Th className="text-right">Anggaran</Th>
                <Th>Status</Th>
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
                <TableMessage columns={COLUMNS}>Tidak ada proyek yang cocok dengan filter.</TableMessage>
              )}
              {items.map((p) => (
                <tr key={p.id} className="hover:bg-surface-muted/50">
                  <Td>
                    <Link href={`/proyek/${p.id}`} className="font-medium text-primary hover:underline">
                      {p.name}
                    </Link>
                    <div className="text-xs text-muted">{p.number}</div>
                  </Td>
                  <Td>{p.client?.name ?? "—"}</Td>
                  <Td>{PROJECT_TYPE[p.project_type]}</Td>
                  <Td className="text-xs">
                    {p.start_date ? formatTanggal(p.start_date) : "—"}
                    {p.end_date && <div className="text-muted">s.d. {formatTanggal(p.end_date)}</div>}
                  </Td>
                  <Td className="tabular text-right">
                    {formatMoney(p.budget_amount, p.currency)}
                  </Td>
                  <Td>
                    <StatusBadge tone={PROJECT_STATUS[p.status].tone}>
                      {PROJECT_STATUS[p.status].label}
                    </StatusBadge>
                  </Td>
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
    </div>
  );
}
