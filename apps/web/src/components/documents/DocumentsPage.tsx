"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Download, FileText } from "lucide-react";
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
import { documentFileUrl } from "@/lib/documents";
import { formatMoney, formatTanggalWaktu } from "@/lib/format";
import { DOCUMENT_STATUS, DOCUMENT_TYPE } from "@/lib/labels";
import type { IssuedDocument, Page } from "@/lib/types";

const PAGE_SIZE = 20;
const COLUMNS = 6;
const DOWNLOAD =
  "inline-flex h-7 items-center gap-1 rounded-md border border-border px-2 text-xs font-medium hover:bg-surface-muted";

export function DocumentsPage() {
  const [q, setQ] = useState("");
  const initial = useSearchParams().get("status") ?? "";
  const [status, setStatus] = useState(initial in DOCUMENT_STATUS ? initial : "");
  const [page, setPage] = useState(1);

  const list = useQuery({
    queryKey: ["documents", "list", { q, status, page }],
    queryFn: ({ signal }) =>
      api.get<Page<IssuedDocument>>(
        `/documents${queryString({ q, status, page, page_size: PAGE_SIZE })}`,
        { signal },
      ),
    placeholderData: keepPreviousData,
  });
  const items = list.data?.items ?? [];
  const filtered = q !== "" || status !== "";

  return (
    <div className="space-y-5">
      <PageHeader
        title="Dokumen"
        description="Dokumen terbit beserta snapshot dan berkas PDF/XLSX yang disimpan saat penerbitan."
      />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput
          value={q}
          onChange={(value) => {
            setQ(value);
            setPage(1);
          }}
          placeholder="Cari nomor atau judul…"
          label="Cari dokumen"
        />
        <Select
          aria-label="Filter status dokumen"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
          className="sm:w-44"
        >
          <option value="">Semua status</option>
          <option value="issued">Terbit</option>
          <option value="void">Dibatalkan</option>
        </Select>
      </div>

      {list.isSuccess && list.data.total === 0 && !filtered ? (
        <EmptyState
          icon={FileText}
          title="Belum ada dokumen terbit"
          description="Dokumen RAB diterbitkan dari halaman RAB setelah versinya disetujui."
        />
      ) : (
        <>
          <Table label="Daftar dokumen">
            <thead>
              <tr>
                <Th>Nomor</Th>
                <Th>Judul</Th>
                <Th className="text-right">Nilai</Th>
                <Th>Status</Th>
                <Th>Diterbitkan</Th>
                <Th className="text-right">Berkas</Th>
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
                <TableMessage columns={COLUMNS}>Tidak ada dokumen yang cocok dengan filter.</TableMessage>
              )}
              {items.map((d) => (
                <tr key={d.id} className="hover:bg-surface-muted/50">
                  <Td>
                    <Link href={`/dokumen/${d.id}`} className="font-mono text-xs font-medium text-primary hover:underline">
                      {d.number}
                    </Link>
                    <div className="text-xs text-muted">{DOCUMENT_TYPE[d.doc_type]}</div>
                  </Td>
                  <Td>{d.title}</Td>
                  <Td className="text-right tabular whitespace-nowrap">{formatMoney(d.total_amount, d.currency)}</Td>
                  <Td>
                    <StatusBadge tone={DOCUMENT_STATUS[d.status].tone}>{DOCUMENT_STATUS[d.status].label}</StatusBadge>
                  </Td>
                  <Td className="text-xs">
                    <div>{formatTanggalWaktu(d.issued_at)}</div>
                    <div className="text-muted">{d.issued_by?.full_name ?? "—"}</div>
                  </Td>
                  <Td className="text-right">
                    <div className="flex justify-end gap-1">
                      {d.files.map((f) => (
                        <a
                          key={f.format}
                          href={documentFileUrl(d.id, f.format, f.format === "xlsx")}
                          target={f.format === "pdf" ? "_blank" : undefined}
                          rel="noopener"
                          className={DOWNLOAD}
                          aria-label={`Unduh ${f.format.toUpperCase()} ${d.number}`}
                        >
                          <Download aria-hidden className="size-3" />
                          {f.format.toUpperCase()}
                        </a>
                      ))}
                    </div>
                  </Td>
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
