"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Pencil, Plus, Truck } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Select } from "@/components/ui/Field";
import { Pagination } from "@/components/ui/Pagination";
import { SearchInput } from "@/components/ui/SearchInput";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { SkeletonRows, Table, TableMessage, Td, Th } from "@/components/ui/Table";
import { api, errorMessage, queryString } from "@/lib/api";
import { useCan } from "@/lib/auth";
import type { Page, Supplier } from "@/lib/types";
import { SupplierFormDialog } from "./SupplierFormDialog";

const PAGE_SIZE = 20;
const COLUMNS = 5;

export function SuppliersPanel() {
  const canWrite = useCan("pricing.write");
  const [q, setQ] = useState("");
  const [active, setActive] = useState<"" | "true" | "false">("true");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Supplier | null>(null);
  const [formOpen, setFormOpen] = useState(false);

  const list = useQuery({
    queryKey: ["suppliers", "list", { q, active, page }],
    queryFn: ({ signal }) =>
      api.get<Page<Supplier>>(
        `/suppliers${queryString({ q, is_active: active, page, page_size: PAGE_SIZE, sort: "name" })}`,
        { signal },
      ),
    placeholderData: keepPreviousData,
  });

  const items = list.data?.items ?? [];
  const filtered = q !== "" || active !== "true";
  const openForm = (supplier: Supplier | null) => {
    setEditing(supplier);
    setFormOpen(true);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput
          value={q}
          onChange={(value) => {
            setQ(value);
            setPage(1);
          }}
          placeholder="Cari nama, kontak, kota…"
          label="Cari supplier"
        />
        <Select
          aria-label="Filter status supplier"
          value={active}
          onChange={(e) => {
            setActive(e.target.value as typeof active);
            setPage(1);
          }}
          className="sm:w-36"
        >
          <option value="true">Aktif</option>
          <option value="false">Nonaktif</option>
          <option value="">Semua</option>
        </Select>
        {canWrite && (
          <Button className="sm:ml-auto" onClick={() => openForm(null)}>
            <Plus aria-hidden className="size-4" />
            Tambah supplier
          </Button>
        )}
      </div>

      {list.isSuccess && list.data.total === 0 && !filtered ? (
        <EmptyState
          icon={Truck}
          title="Belum ada supplier"
          description="Supplier dipakai sebagai sumber harga agar harga dapat diverifikasi."
        />
      ) : (
        <>
          <Table label="Daftar supplier">
            <thead>
              <tr>
                <Th>Nama</Th>
                <Th>Kontak</Th>
                <Th>Kota</Th>
                <Th>Status</Th>
                <Th className="text-right">
                  <span className="sr-only">Aksi</span>
                </Th>
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
                <TableMessage columns={COLUMNS}>Tidak ada supplier yang cocok dengan filter.</TableMessage>
              )}
              {items.map((supplier) => (
                <tr key={supplier.id} className="hover:bg-surface-muted/50">
                  <Td className="font-medium">{supplier.name}</Td>
                  <Td>
                    <div>{supplier.contact_person ?? "—"}</div>
                    <div className="text-xs text-muted">{supplier.phone ?? supplier.email ?? ""}</div>
                  </Td>
                  <Td>{supplier.city ?? "—"}</Td>
                  <Td>
                    <StatusBadge tone={supplier.is_active ? "success" : "neutral"}>
                      {supplier.is_active ? "Aktif" : "Nonaktif"}
                    </StatusBadge>
                  </Td>
                  <Td className="text-right">
                    {canWrite && (
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Ubah ${supplier.name}`}
                        onClick={() => openForm(supplier)}
                      >
                        <Pencil className="size-4" />
                      </Button>
                    )}
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

      <SupplierFormDialog open={formOpen} supplier={editing} onClose={() => setFormOpen(false)} />
    </div>
  );
}
