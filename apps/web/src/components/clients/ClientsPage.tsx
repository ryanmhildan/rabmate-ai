"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { Select } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { Pagination } from "@/components/ui/Pagination";
import { SearchInput } from "@/components/ui/SearchInput";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { SkeletonRows, Table, TableMessage, Td, Th } from "@/components/ui/Table";
import { api, errorMessage, queryString } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { CLIENT_TYPE } from "@/lib/labels";
import type { Client, Page } from "@/lib/types";
import { ClientFormDialog } from "./ClientFormDialog";

const PAGE_SIZE = 20;
const COLUMNS = 6;

export function ClientsPage() {
  const canWrite = useCan("clients.write");
  const canDelete = useCan("clients.delete");
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [active, setActive] = useState<"" | "true" | "false">("true");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Client | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [deleting, setDeleting] = useState<Client | null>(null);

  const list = useQuery({
    queryKey: ["clients", { q, active, page }],
    queryFn: ({ signal }) =>
      api.get<Page<Client>>(
        `/clients${queryString({ q, is_active: active, page, page_size: PAGE_SIZE, sort: "name" })}`,
        { signal },
      ),
    placeholderData: keepPreviousData,
  });

  const remove = useMutation({
    mutationFn: (client: Client) => api.delete(`/clients/${client.id}`),
    onSuccess: (_, client) => {
      void queryClient.invalidateQueries({ queryKey: ["clients"] });
      toast.success(`Klien ${client.name} dihapus.`);
      setDeleting(null);
    },
    onError: (error) => {
      toast.error(errorMessage(error));
      setDeleting(null);
    },
  });

  const filtered = q !== "" || active !== "true";
  const items = list.data?.items ?? [];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Klien"
        description="Data klien untuk proyek, penawaran, dan invoice."
        actions={
          canWrite && (
            <Button
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              <Plus aria-hidden className="size-4" />
              Tambah klien
            </Button>
          )
        }
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput
          value={q}
          onChange={(value) => {
            setQ(value);
            setPage(1);
          }}
          placeholder="Cari nama, kode, kontak, kota…"
          label="Cari klien"
        />
        <Select
          aria-label="Filter status klien"
          value={active}
          onChange={(event) => {
            setActive(event.target.value as typeof active);
            setPage(1);
          }}
          className="sm:w-44"
        >
          <option value="true">Aktif</option>
          <option value="false">Nonaktif</option>
          <option value="">Semua</option>
        </Select>
      </div>

      {list.isSuccess && list.data.total === 0 && !filtered ? (
        <EmptyState
          icon={Building2}
          title="Belum ada klien"
          description={
            canWrite
              ? "Tambahkan klien pertama untuk mulai membuat proyek."
              : "Belum ada klien. Hubungi pengguna yang berwenang untuk menambahkannya."
          }
        />
      ) : (
        <>
          <Table label="Daftar klien">
            <thead>
              <tr>
                <Th>Nama</Th>
                <Th>Jenis</Th>
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
                  <span className="text-danger">{errorMessage(list.error)}</span>{" "}
                  <Button variant="ghost" size="sm" onClick={() => void list.refetch()}>
                    Coba lagi
                  </Button>
                </TableMessage>
              )}
              {list.isSuccess && items.length === 0 && (
                <TableMessage columns={COLUMNS}>Tidak ada klien yang cocok dengan filter.</TableMessage>
              )}
              {items.map((client) => (
                <tr key={client.id} className="hover:bg-surface-muted/50">
                  <Td>
                    <div className="font-medium">{client.name}</div>
                    {client.code && <div className="text-xs text-muted">{client.code}</div>}
                  </Td>
                  <Td>{CLIENT_TYPE[client.client_type]}</Td>
                  <Td>
                    <div>{client.contact_person ?? "—"}</div>
                    <div className="text-xs text-muted">{client.email ?? client.phone ?? ""}</div>
                  </Td>
                  <Td>{client.city ?? "—"}</Td>
                  <Td>
                    <StatusBadge tone={client.is_active ? "success" : "neutral"}>
                      {client.is_active ? "Aktif" : "Nonaktif"}
                    </StatusBadge>
                  </Td>
                  <Td className="text-right">
                    <div className="flex justify-end gap-1">
                      {canWrite && (
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Ubah ${client.name}`}
                          onClick={() => {
                            setEditing(client);
                            setFormOpen(true);
                          }}
                        >
                          <Pencil className="size-4" />
                        </Button>
                      )}
                      {canDelete && (
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Hapus ${client.name}`}
                          onClick={() => setDeleting(client)}
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      )}
                    </div>
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

      <ClientFormDialog client={editing} open={formOpen} onClose={() => setFormOpen(false)} />
      <ConfirmDialog
        open={deleting !== null}
        title="Hapus klien?"
        message={
          <>
            Klien <strong>{deleting?.name}</strong> akan dihapus permanen. Klien yang sudah dipakai
            proyek tidak dapat dihapus — nonaktifkan saja melalui tombol ubah.
          </>
        }
        confirmLabel="Hapus"
        danger
        loading={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
        onClose={() => setDeleting(null)}
      />
    </div>
  );
}
