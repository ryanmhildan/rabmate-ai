"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Plus, Receipt } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { VoidDocumentDialog } from "@/components/documents/VoidDocumentDialog";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { Field, FormError, Input, Select } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { Pagination } from "@/components/ui/Pagination";
import { SearchInput } from "@/components/ui/SearchInput";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { SkeletonRows, Table, TableMessage, Td, Th } from "@/components/ui/Table";
import { api, errorMessage, queryString } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { formatMoney, formatTanggal } from "@/lib/format";
import { applyServerErrors } from "@/lib/forms";
import { DOC_STATUS, PAYMENT_METHOD, PAYMENT_STATE, options } from "@/lib/labels";
import type { Invoice, InvoiceListItem, Page, Payment, ProjectListItem } from "@/lib/types";

const PAGE_SIZE = 20;

export function InvoicesPage() {
  const initial = useSearchParams().get("tab") === "pembayaran" ? "payments" : "invoices";
  const [tab, setTab] = useState<"invoices" | "payments">(initial);
  return (
    <div className="space-y-5">
      <PageHeader
        title="Invoice & Pembayaran"
        description="Tagihan per termin atau manual, pembayaran yang diterima, dan sisa tagihan."
      />
      <div role="tablist" aria-label="Bagian invoice" className="flex gap-1 border-b border-border">
        {(
          [
            ["invoices", "Invoice"],
            ["payments", "Pembayaran"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              tab === key ? "border-primary text-foreground" : "border-transparent text-muted hover:text-foreground"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "invoices" ? <InvoiceList /> : <PaymentList />}
    </div>
  );
}

function InvoiceList() {
  const canWrite = useCan("finance.write");
  const search = useSearchParams();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [paymentState, setPaymentState] = useState(search.get("payment_state") ?? "");
  const [overdue, setOverdue] = useState(search.get("overdue") === "true");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const list = useQuery({
    queryKey: ["invoices", "list", { q, status, paymentState, overdue, page }],
    queryFn: ({ signal }) =>
      api.get<Page<InvoiceListItem>>(
        `/invoices${queryString({ q, status, payment_state: paymentState, overdue: overdue || undefined, page, page_size: PAGE_SIZE })}`,
        { signal },
      ),
    placeholderData: keepPreviousData,
  });
  const items = list.data?.items ?? [];
  const filtered = q !== "" || status !== "" || paymentState !== "" || overdue;
  const reset = () => setPage(1);

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <SearchInput
          value={q}
          onChange={(v) => {
            setQ(v);
            reset();
          }}
          placeholder="Cari nomor atau judul…"
          label="Cari invoice"
        />
        <Select aria-label="Filter status invoice" value={status} onChange={(e) => { setStatus(e.target.value); reset(); }} className="lg:w-44">
          <option value="">Semua status</option>
          {options(DOC_STATUS).map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
        <Select aria-label="Filter pembayaran" value={paymentState} onChange={(e) => { setPaymentState(e.target.value); reset(); }} className="lg:w-44">
          <option value="">Semua pembayaran</option>
          {options(PAYMENT_STATE).map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="size-4 accent-primary" checked={overdue} onChange={(e) => { setOverdue(e.target.checked); reset(); }} />
          Hanya lewat jatuh tempo
        </label>
        {canWrite && (
          <Button className="lg:ml-auto" onClick={() => setCreating(true)}>
            <Plus aria-hidden className="size-4" />
            Invoice manual
          </Button>
        )}
      </div>

      {list.isSuccess && list.data.total === 0 && !filtered ? (
        <EmptyState
          icon={Receipt}
          title="Belum ada invoice"
          description="Invoice termin dibuat dari penawaran yang diterima klien; invoice manual dibuat untuk proyek."
        />
      ) : (
        <>
          <Table label="Daftar invoice">
            <thead>
              <tr>
                <Th>Nomor</Th>
                <Th>Judul / klien</Th>
                <Th className="text-right">Total</Th>
                <Th className="text-right">Sisa</Th>
                <Th>Status</Th>
                <Th>Jatuh tempo</Th>
              </tr>
            </thead>
            <tbody>
              {list.isPending && <SkeletonRows columns={6} />}
              {list.isError && (
                <TableMessage columns={6}>
                  <span className="text-danger">{errorMessage(list.error)}</span>
                </TableMessage>
              )}
              {list.isSuccess && items.length === 0 && <TableMessage columns={6}>Tidak ada invoice yang cocok.</TableMessage>}
              {items.map((x) => (
                <tr key={x.id} className="hover:bg-surface-muted/50">
                  <Td>
                    <Link href={`/invoice/${x.id}`} className="font-mono text-xs font-medium text-primary hover:underline">
                      {x.number ?? "(belum bernomor)"}
                    </Link>
                    <div className="text-xs text-muted">{x.kind === "term" ? "Termin" : "Manual"}</div>
                  </Td>
                  <Td>
                    {x.title}
                    <div className="text-xs text-muted">{x.client.name}</div>
                  </Td>
                  <Td className="text-right tabular whitespace-nowrap">{formatMoney(x.grand_total, x.currency)}</Td>
                  <Td className="text-right tabular whitespace-nowrap">
                    {x.status === "issued" ? formatMoney(x.outstanding, x.currency) : "—"}
                  </Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      <StatusBadge tone={DOC_STATUS[x.status].tone}>{DOC_STATUS[x.status].label}</StatusBadge>
                      {x.payment_state && (
                        <StatusBadge tone={PAYMENT_STATE[x.payment_state].tone}>{PAYMENT_STATE[x.payment_state].label}</StatusBadge>
                      )}
                      {x.overdue && <StatusBadge tone="danger">Lewat jatuh tempo</StatusBadge>}
                    </div>
                  </Td>
                  <Td className="text-xs whitespace-nowrap">{x.due_date ? formatTanggal(x.due_date) : "—"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          {list.data && (
            <Pagination page={list.data.page} pageSize={list.data.page_size} total={list.data.total} onPageChange={setPage} />
          )}
        </>
      )}
      <NewInvoiceDialog open={creating} onClose={() => setCreating(false)} />
    </div>
  );
}

const newInvoiceSchema = z.object({
  project_id: z.string().min(1, "Pilih proyek."),
  title: z.string().trim().min(1, "Judul wajib diisi.").max(300),
  due_date: z.string(),
});

function NewInvoiceDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} title="Invoice manual">
      {open && <NewInvoiceForm onClose={onClose} />}
    </Dialog>
  );
}

function NewInvoiceForm({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const projects = useQuery({
    queryKey: ["projects", "options"],
    queryFn: () => api.get<Page<ProjectListItem>>("/projects?page_size=100&sort=name"),
  });
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<z.infer<typeof newInvoiceSchema>>({
    resolver: zodResolver(newInvoiceSchema),
    defaultValues: { project_id: "", title: "", due_date: "" },
  });
  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const invoice = await api.post<Invoice>("/invoices", { ...values, due_date: values.due_date || null });
      void queryClient.invalidateQueries({ queryKey: ["invoices"] });
      onClose();
      router.push(`/invoice/${invoice.id}`);
    } catch (error) {
      setFormError(applyServerErrors(error, setError, Object.keys(newInvoiceSchema.shape)));
    }
  });
  const withClient = (projects.data?.items ?? []).filter((p) => p.client);
  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormError message={formError} />
      <p className="text-sm text-muted">
        Untuk tagihan di luar jadwal termin. Klien dan pajak diambil dari proyek; baris tagihan diisi
        setelah dibuat.
      </p>
      <Field label="Proyek" error={errors.project_id?.message} required hint="Hanya proyek yang sudah memiliki klien.">
        {(a) => (
          <Select {...a} {...register("project_id")} disabled={projects.isPending}>
            <option value="">— Pilih proyek —</option>
            {withClient.map((p) => (
              <option key={p.id} value={p.id}>
                {p.number} — {p.name} ({p.client?.name})
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="Judul" error={errors.title?.message} required>
        {(a) => <Input {...a} {...register("title")} />}
      </Field>
      <Field label="Jatuh tempo" error={errors.due_date?.message}>
        {(a) => <Input type="date" {...a} {...register("due_date")} />}
      </Field>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
          Batal
        </Button>
        <Button type="submit" loading={isSubmitting}>
          Buat invoice
        </Button>
      </div>
    </form>
  );
}

function PaymentList() {
  const canWrite = useCan("finance.write");
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [voiding, setVoiding] = useState<Payment | null>(null);
  const list = useQuery({
    queryKey: ["payments", "list", { page }],
    queryFn: ({ signal }) => api.get<Page<Payment>>(`/payments${queryString({ page, page_size: PAGE_SIZE })}`, { signal }),
    placeholderData: keepPreviousData,
  });
  const items = list.data?.items ?? [];
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">
        Pembayaran dicatat dari halaman invoice. Pembayaran tidak dapat diubah atau dihapus; kesalahan
        dibatalkan dengan alasan dan alokasinya dilepas.
      </p>
      <Table label="Daftar pembayaran">
        <thead>
          <tr>
            <Th>Tanggal</Th>
            <Th>Klien</Th>
            <Th className="text-right">Jumlah</Th>
            <Th>Metode / referensi</Th>
            <Th>Dialokasikan ke</Th>
            <Th>Status</Th>
            <Th className="text-right">
              <span className="sr-only">Aksi</span>
            </Th>
          </tr>
        </thead>
        <tbody>
          {list.isPending && <SkeletonRows columns={7} />}
          {list.isSuccess && items.length === 0 && <TableMessage columns={7}>Belum ada pembayaran.</TableMessage>}
          {items.map((p) => (
            <tr key={p.id} className="align-top hover:bg-surface-muted/50">
              <Td className="whitespace-nowrap">{formatTanggal(p.payment_date)}</Td>
              <Td>{p.client.name}</Td>
              <Td className="text-right tabular whitespace-nowrap">
                {formatMoney(p.amount, p.currency)}
                {p.status === "recorded" && p.unallocated !== "0.00" && (
                  <div className="text-xs text-warning">Belum dialokasikan {formatMoney(p.unallocated, p.currency)}</div>
                )}
              </Td>
              <Td className="text-xs">
                {PAYMENT_METHOD[p.method]}
                {p.reference && <div className="text-muted">{p.reference}</div>}
              </Td>
              <Td className="text-xs">
                {p.allocations.map((a) => (
                  <div key={a.invoice_id}>
                    <Link href={`/invoice/${a.invoice_id}`} className="text-primary hover:underline">
                      {a.invoice_number ?? "Invoice"}
                    </Link>{" "}
                    {formatMoney(a.amount, p.currency)}
                  </div>
                ))}
              </Td>
              <Td>
                <StatusBadge tone={p.status === "recorded" ? "success" : "danger"}>
                  {p.status === "recorded" ? "Tercatat" : "Dibatalkan"}
                </StatusBadge>
                {p.void_reason && <div className="mt-1 text-xs text-muted">“{p.void_reason}”</div>}
              </Td>
              <Td className="text-right">
                {canWrite && p.status === "recorded" && (
                  <Button variant="ghost" size="sm" aria-label={`Batalkan pembayaran ${formatTanggal(p.payment_date)}`} onClick={() => setVoiding(p)}>
                    <Ban className="size-4" />
                  </Button>
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {list.data && (
        <Pagination page={list.data.page} pageSize={list.data.page_size} total={list.data.total} onPageChange={setPage} />
      )}
      <VoidDocumentDialog
        number={voiding ? formatMoney(voiding.amount, voiding.currency) : null}
        title="Batalkan pembayaran"
        confirmLabel="Batalkan pembayaran"
        message={
          voiding && (
            <>
              Pembayaran <strong>{formatMoney(voiding.amount, voiding.currency)}</strong> dari {voiding.client.name} (
              {formatTanggal(voiding.payment_date)}) akan dibatalkan. Sisa tagihan invoice terkait kembali bertambah.
            </>
          )
        }
        onClose={() => setVoiding(null)}
        onConfirm={async (reason) => {
          if (!voiding) return;
          await api.post<Payment>(`/payments/${voiding.id}/void`, { reason });
          void queryClient.invalidateQueries({ queryKey: ["payments"] });
          void queryClient.invalidateQueries({ queryKey: ["invoices"] });
          toast.success("Pembayaran dibatalkan.");
        }}
      />
    </div>
  );
}
