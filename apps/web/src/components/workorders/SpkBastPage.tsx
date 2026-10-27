"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ClipboardList, Handshake } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Select } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { Pagination } from "@/components/ui/Pagination";
import { SearchInput } from "@/components/ui/SearchInput";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { SkeletonRows, Table, TableMessage, Td, Th } from "@/components/ui/Table";
import { TAB_LIST, tabClass } from "@/components/ui/Tabs";
import { api, errorMessage, queryString } from "@/lib/api";
import { formatMoney, formatTanggal } from "@/lib/format";
import { BAST_KIND, DOC_STATUS, options } from "@/lib/labels";
import type { BastListItem, Page, SpkListItem } from "@/lib/types";

const PAGE_SIZE = 20;

export function SpkBastPage() {
  const initial = useSearchParams().get("tab") === "bast" ? "bast" : "spk";
  const [tab, setTab] = useState<"spk" | "bast">(initial);
  return (
    <div className="space-y-5">
      <PageHeader
        title="SPK & BAST"
        description="Surat perintah kerja dari penawaran yang diterima klien, dan berita acara serah terima pekerjaan/barang."
      />
      <div role="tablist" aria-label="Bagian SPK dan BAST" className={TAB_LIST}>
        {(
          [
            ["spk", "SPK"],
            ["bast", "BAST"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={tabClass(tab === key)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "spk" ? <SpkList /> : <BastList />}
    </div>
  );
}

function Filters({
  q,
  status,
  onQ,
  onStatus,
  placeholder,
  children,
}: {
  q: string;
  status: string;
  onQ: (value: string) => void;
  onStatus: (value: string) => void;
  placeholder: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
      <SearchInput value={q} onChange={onQ} placeholder={placeholder} label={placeholder} />
      <Select aria-label="Filter status" value={status} onChange={(e) => onStatus(e.target.value)} className="sm:w-48">
        <option value="">Semua status</option>
        {options(DOC_STATUS).map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </Select>
      {children}
    </div>
  );
}

function SpkList() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const list = useQuery({
    queryKey: ["spk", "list", { q, status, page }],
    queryFn: ({ signal }) =>
      api.get<Page<SpkListItem>>(`/spk${queryString({ q, status, page, page_size: PAGE_SIZE })}`, { signal }),
    placeholderData: keepPreviousData,
  });
  const items = list.data?.items ?? [];
  const columns = 6;

  if (list.isSuccess && list.data.total === 0 && !q && !status) {
    return (
      <EmptyState
        icon={Handshake}
        title="Belum ada SPK"
        description={
          <>
            SPK dibuat dari penawaran yang sudah terbit dan diterima klien (halaman penawaran → Buat SPK).{" "}
            <Link href="/penawaran" className="text-primary hover:underline">
              Lihat penawaran
            </Link>
          </>
        }
      />
    );
  }
  return (
    <div className="space-y-4">
      <Filters
        q={q}
        status={status}
        placeholder="Cari nomor atau judul SPK…"
        onQ={(value) => {
          setQ(value);
          setPage(1);
        }}
        onStatus={(value) => {
          setStatus(value);
          setPage(1);
        }}
      />
      <Table label="Daftar SPK">
        <thead>
          <tr>
            <Th>Nomor</Th>
            <Th>Pekerjaan</Th>
            <Th>Klien</Th>
            <Th className="text-right">Nilai kontrak</Th>
            <Th>Status</Th>
            <Th>Jangka waktu</Th>
          </tr>
        </thead>
        <tbody>
          {list.isPending && <SkeletonRows columns={columns} />}
          {list.isError && (
            <TableMessage columns={columns}>
              <span className="text-danger">{errorMessage(list.error)}</span>{" "}
              <Button variant="ghost" size="sm" onClick={() => void list.refetch()}>
                Coba lagi
              </Button>
            </TableMessage>
          )}
          {list.isSuccess && items.length === 0 && (
            <TableMessage columns={columns}>Tidak ada SPK yang cocok dengan filter.</TableMessage>
          )}
          {items.map((x) => (
            <tr key={x.id} className="hover:bg-surface-muted/50">
              <Td>
                <Link href={`/spk-bast/spk/${x.id}`} className="font-mono text-xs font-medium whitespace-nowrap text-primary hover:underline">
                  {x.number ?? "Draft"}
                </Link>
                <div className="text-xs text-muted">{x.quotation.number}</div>
              </Td>
              <Td>
                {x.title}
                <div className="text-xs text-muted">{x.project.name}</div>
              </Td>
              <Td>{x.client.name}</Td>
              <Td className="text-right tabular whitespace-nowrap">{formatMoney(x.contract_value, x.currency)}</Td>
              <Td>
                <div className="flex flex-wrap gap-1">
                  <StatusBadge tone={DOC_STATUS[x.status].tone}>{DOC_STATUS[x.status].label}</StatusBadge>
                  {x.bast_count > 0 && <StatusBadge tone="neutral">{`${x.bast_count} BAST`}</StatusBadge>}
                </div>
              </Td>
              <Td className="text-xs whitespace-nowrap">
                {x.start_date ? formatTanggal(x.start_date) : "-"}
                {x.end_date && ` – ${formatTanggal(x.end_date)}`}
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {list.data && (
        <Pagination page={list.data.page} pageSize={list.data.page_size} total={list.data.total} onPageChange={setPage} />
      )}
    </div>
  );
}

function BastList() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const [page, setPage] = useState(1);
  const list = useQuery({
    queryKey: ["bast", "list", { q, status, kind, page }],
    queryFn: ({ signal }) =>
      api.get<Page<BastListItem>>(`/bast${queryString({ q, status, kind, page, page_size: PAGE_SIZE })}`, { signal }),
    placeholderData: keepPreviousData,
  });
  const items = list.data?.items ?? [];
  const columns = 6;

  if (list.isSuccess && list.data.total === 0 && !q && !status && !kind) {
    return (
      <EmptyState
        icon={ClipboardList}
        title="Belum ada BAST"
        description="BAST dibuat dari SPK yang sudah terbit (halaman SPK → Buat BAST), berisi pekerjaan/barang yang benar-benar diserahkan."
      />
    );
  }
  return (
    <div className="space-y-4">
      <Filters
        q={q}
        status={status}
        placeholder="Cari nomor atau judul BAST…"
        onQ={(value) => {
          setQ(value);
          setPage(1);
        }}
        onStatus={(value) => {
          setStatus(value);
          setPage(1);
        }}
      >
        <Select
          aria-label="Filter jenis BAST"
          value={kind}
          onChange={(e) => {
            setKind(e.target.value);
            setPage(1);
          }}
          className="sm:w-56"
        >
          <option value="">Semua jenis</option>
          {options(BAST_KIND).map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </Filters>
      <Table label="Daftar BAST">
        <thead>
          <tr>
            <Th>Nomor</Th>
            <Th>Judul</Th>
            <Th>Klien</Th>
            <Th>Jenis</Th>
            <Th>Status</Th>
            <Th>Tanggal serah terima</Th>
          </tr>
        </thead>
        <tbody>
          {list.isPending && <SkeletonRows columns={columns} />}
          {list.isError && (
            <TableMessage columns={columns}>
              <span className="text-danger">{errorMessage(list.error)}</span>{" "}
              <Button variant="ghost" size="sm" onClick={() => void list.refetch()}>
                Coba lagi
              </Button>
            </TableMessage>
          )}
          {list.isSuccess && items.length === 0 && (
            <TableMessage columns={columns}>Tidak ada BAST yang cocok dengan filter.</TableMessage>
          )}
          {items.map((x) => (
            <tr key={x.id} className="hover:bg-surface-muted/50">
              <Td>
                <Link href={`/spk-bast/bast/${x.id}`} className="font-mono text-xs font-medium whitespace-nowrap text-primary hover:underline">
                  {x.number ?? "Draft"}
                </Link>
                <div className="text-xs text-muted">{x.spk.number}</div>
              </Td>
              <Td>
                {x.title}
                <div className="text-xs text-muted">
                  {x.project.name} · {x.item_count} baris
                </div>
              </Td>
              <Td>{x.client.name}</Td>
              <Td className="text-xs">{BAST_KIND[x.kind]}</Td>
              <Td>
                <StatusBadge tone={DOC_STATUS[x.status].tone}>{DOC_STATUS[x.status].label}</StatusBadge>
              </Td>
              <Td className="text-xs whitespace-nowrap">{x.handover_date ? formatTanggal(x.handover_date) : "-"}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {list.data && (
        <Pagination page={list.data.page} pageSize={list.data.page_size} total={list.data.total} onPageChange={setPage} />
      )}
    </div>
  );
}
