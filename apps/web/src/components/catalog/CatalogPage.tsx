"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, Info, PackageSearch, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button, buttonClass } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Select } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { Pagination } from "@/components/ui/Pagination";
import { SearchInput } from "@/components/ui/SearchInput";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { SkeletonRows, Table, TableMessage, Td, Th } from "@/components/ui/Table";
import { TAB_LIST, tabClass } from "@/components/ui/Tabs";
import { api, errorMessage, queryString } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { RAB_ITEM_TYPE, options } from "@/lib/labels";
import type { CatalogItemDetail, CatalogListItem, ExternalSearchStatus, Page } from "@/lib/types";
import { CatalogItemFormDialog } from "./CatalogItemFormDialog";
import { PriceWithStatus } from "./PriceBits";
import { SuppliersPanel } from "./SuppliersPanel";

const PAGE_SIZE = 20;
const COLUMNS = 5;

export function CatalogPage() {
  const canWrite = useCan("pricing.write");
  const [tab, setTab] = useState<"items" | "suppliers">("items");

  return (
    <div className="space-y-5">
      <PageHeader
        title="Katalog Harga"
        description="Harga material, jasa, dan peralatan beserta sumber dan status verifikasinya."
        actions={
          canWrite && (
            <Link href="/katalog-harga/impor" className={buttonClass({ variant: "secondary" })}>
              <FileSpreadsheet aria-hidden className="size-4" />
              Impor spreadsheet
            </Link>
          )
        }
      />
      <ExternalSearchBanner />
      <div role="tablist" aria-label="Bagian katalog" className={TAB_LIST}>
        {(
          [
            ["items", "Item & harga"],
            ["suppliers", "Supplier"],
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
      {tab === "items" ? <CatalogItemsPanel /> : <SuppliersPanel />}
    </div>
  );
}

/** States plainly that no external price search is configured, instead of pretending to search. */
function ExternalSearchBanner() {
  const status = useQuery({
    queryKey: ["price-sources", "external"],
    queryFn: () => api.get<ExternalSearchStatus>("/price-sources/external"),
    staleTime: 5 * 60_000,
  });
  if (!status.data || status.data.configured) return null;
  return (
    <div className="flex items-start gap-2 rounded-md border border-border bg-surface-muted px-3 py-2 text-sm text-muted">
      <Info aria-hidden className="mt-0.5 size-4 shrink-0" />
      <span>{status.data.message}</span>
    </div>
  );
}

function CatalogItemsPanel() {
  const canWrite = useCan("pricing.write");
  const router = useRouter();
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [itemType, setItemType] = useState("");
  const [active, setActive] = useState<"" | "true" | "false">("true");
  const [page, setPage] = useState(1);
  const [formOpen, setFormOpen] = useState(false);

  const list = useQuery({
    queryKey: ["price-catalog", "list", { q, category, itemType, active, page }],
    queryFn: ({ signal }) =>
      api.get<Page<CatalogListItem>>(
        `/price-catalog${queryString({
          q,
          category,
          item_type: itemType,
          is_active: active,
          page,
          page_size: PAGE_SIZE,
          sort: "name",
        })}`,
        { signal },
      ),
    placeholderData: keepPreviousData,
  });
  const categories = useQuery({
    queryKey: ["price-catalog", "categories"],
    queryFn: () => api.get<string[]>("/price-catalog/categories"),
  });

  const filtered = q !== "" || category !== "" || itemType !== "" || active !== "true";
  const items = list.data?.items ?? [];
  const reset = () => setPage(1);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <SearchInput
          value={q}
          onChange={(value) => {
            setQ(value);
            reset();
          }}
          placeholder="Cari nama, kode, merek, spesifikasi…"
          label="Cari item katalog"
        />
        <Select
          aria-label="Filter kategori"
          value={category}
          onChange={(e) => {
            setCategory(e.target.value);
            reset();
          }}
          className="lg:w-44"
        >
          <option value="">Semua kategori</option>
          {categories.data?.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Filter jenis"
          value={itemType}
          onChange={(e) => {
            setItemType(e.target.value);
            reset();
          }}
          className="lg:w-40"
        >
          <option value="">Semua jenis</option>
          {options(RAB_ITEM_TYPE).map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Filter status item"
          value={active}
          onChange={(e) => {
            setActive(e.target.value as typeof active);
            reset();
          }}
          className="lg:w-36"
        >
          <option value="true">Aktif</option>
          <option value="false">Nonaktif</option>
          <option value="">Semua</option>
        </Select>
        {canWrite && (
          <Button className="lg:ml-auto" onClick={() => setFormOpen(true)}>
            <Plus aria-hidden className="size-4" />
            Tambah item
          </Button>
        )}
      </div>

      {list.isSuccess && list.data.total === 0 && !filtered ? (
        <EmptyState
          icon={PackageSearch}
          title="Katalog masih kosong"
          description={
            canWrite
              ? "Tambahkan item satu per satu atau impor dari spreadsheet."
              : "Belum ada item katalog. Hubungi estimator atau pemilik untuk menambahkannya."
          }
        />
      ) : (
        <>
          <Table label="Daftar item katalog">
            <thead>
              <tr>
                <Th>Item</Th>
                <Th>Kategori</Th>
                <Th>Harga terverifikasi terakhir</Th>
                <Th>Harga terbaru</Th>
                <Th className="text-right">Riwayat</Th>
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
                <TableMessage columns={COLUMNS}>Tidak ada item yang cocok dengan filter.</TableMessage>
              )}
              {items.map((item) => {
                const latest = item.prices.latest_any;
                const showLatest = latest && latest.id !== item.prices.latest_verified?.id;
                return (
                  <tr key={item.id} className="hover:bg-surface-muted/50">
                    <Td>
                      <Link href={`/katalog-harga/${item.id}`} className="font-medium text-primary hover:underline">
                        {item.name}
                      </Link>
                      <div className="text-xs text-muted">
                        {[item.code, item.brand, `per ${item.unit}`, RAB_ITEM_TYPE[item.item_type]]
                          .filter(Boolean)
                          .join(" · ")}
                      </div>
                      {!item.is_active && <StatusBadge tone="neutral">Nonaktif</StatusBadge>}
                    </Td>
                    <Td>{item.category ?? "-"}</Td>
                    <Td>
                      <PriceWithStatus observation={item.prices.latest_verified} />
                    </Td>
                    <Td>
                      {showLatest ? (
                        <PriceWithStatus observation={latest} />
                      ) : (
                        <span className="text-xs text-muted">{latest ? "Sama" : "-"}</span>
                      )}
                    </Td>
                    <Td className="text-right tabular">{item.prices.observation_count}</Td>
                  </tr>
                );
              })}
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

      <CatalogItemFormDialog
        open={formOpen}
        item={null}
        onClose={() => setFormOpen(false)}
        onSubmit={async (payload) => {
          const saved = await api.post<CatalogItemDetail>("/price-catalog", payload);
          void queryClient.invalidateQueries({ queryKey: ["price-catalog"] });
          toast.success(`Item ${saved.name} ditambahkan.`);
          router.push(`/katalog-harga/${saved.id}`);
        }}
      />
    </div>
  );
}
