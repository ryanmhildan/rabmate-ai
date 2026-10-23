"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Ban, Eye, Plus, Stamp, Trash2, Wallet } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { AuditList } from "@/components/audit/AuditList";
import { IssueDocumentDialog } from "@/components/documents/IssueDocumentDialog";
import { VoidDocumentDialog } from "@/components/documents/VoidDocumentDialog";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { Field, FormError, Input, Textarea } from "@/components/ui/Field";
import { FullPageMessage } from "@/components/ui/FullPageMessage";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { API_BASE, ApiError, api, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { formatMoney, formatPercent, formatQuantity, formatTanggal, formatTanggalWaktu, formatUnitPrice } from "@/lib/format";
import { applyServerErrors, blankToNull, decimalString, optionalText, percentString } from "@/lib/forms";
import { DOC_STATUS, PAYMENT_METHOD, PAYMENT_STATE } from "@/lib/labels";
import type { Invoice, Payment } from "@/lib/types";
import { ApprovalTimeline, WorkflowButtons } from "./DocWorkflow";
import { RecordPaymentDialog } from "./RecordPaymentDialog";

const LINK =
  "inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 text-xs font-medium hover:bg-surface-muted";

export function InvoiceDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const canAudit = useCan("audit.read");
  const canWrite = useCan("finance.write");
  const queryKey = ["invoices", "detail", id];
  const [issuing, setIssuing] = useState(false);
  const [voiding, setVoiding] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [paying, setPaying] = useState(false);
  const [voidingPayment, setVoidingPayment] = useState<string | null>(null);

  const detail = useQuery({
    queryKey,
    queryFn: ({ signal }) => api.get<Invoice>(`/invoices/${id}`, { signal }),
    retry: false,
  });

  if (detail.isPending) return <FullPageMessage loading title="Memuat invoice…" />;
  if (detail.isError) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <div className="space-y-4">
        <BackLink />
        <PageHeader title={notFound ? "Invoice tidak ditemukan" : "Invoice gagal dimuat"} description={errorMessage(detail.error)} />
      </div>
    );
  }

  const inv = detail.data;
  const refresh = () => {
    void detail.refetch();
    void queryClient.invalidateQueries({ queryKey: ["invoices", "list"] });
    void queryClient.invalidateQueries({ queryKey: ["payments"] });
    void queryClient.invalidateQueries({ queryKey: ["quotations"] });
    void queryClient.invalidateQueries({ queryKey: ["audit"] });
  };
  const saved = (updated: Invoice) => {
    queryClient.setQueryData(queryKey, updated);
    refresh();
  };

  return (
    <div className="space-y-6">
      <BackLink />
      <PageHeader
        title={inv.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs">{inv.number ?? "(belum bernomor)"}</span>
            <StatusBadge tone={DOC_STATUS[inv.status].tone}>{DOC_STATUS[inv.status].label}</StatusBadge>
            {inv.payment_state && (
              <StatusBadge tone={PAYMENT_STATE[inv.payment_state].tone}>{PAYMENT_STATE[inv.payment_state].label}</StatusBadge>
            )}
            {inv.overdue && <StatusBadge tone="danger">Lewat jatuh tempo</StatusBadge>}
            {inv.quotation && (
              <Link href={`/penawaran/${inv.quotation.id}`} className="text-primary hover:underline">
                {inv.quotation.number}
                {inv.payment_term && ` · ${inv.payment_term.name}`}
              </Link>
            )}
          </span>
        }
        actions={
          <>
            <a href={`${API_BASE}/invoices/${id}/preview.pdf`} target="_blank" rel="noopener" className={LINK}>
              <Eye aria-hidden className="size-3.5" />
              Pratinjau PDF
            </a>
            <WorkflowButtons<Invoice> base={`/invoices/${id}`} actions={inv.allowed_actions} onDone={saved} />
            {inv.can_issue && (
              <Button size="sm" onClick={() => setIssuing(true)}>
                <Stamp aria-hidden className="size-4" />
                Terbitkan
              </Button>
            )}
            {inv.can_record_payment && (
              <Button size="sm" onClick={() => setPaying(true)}>
                <Wallet aria-hidden className="size-4" />
                Catat pembayaran
              </Button>
            )}
            {inv.can_void && (
              <Button size="sm" variant="secondary" onClick={() => setVoiding(true)}>
                <Ban aria-hidden className="size-4" />
                Batalkan
              </Button>
            )}
            {inv.can_delete && (
              <Button size="sm" variant="secondary" onClick={() => setDeleting(true)}>
                <Trash2 aria-hidden className="size-4" />
                Hapus
              </Button>
            )}
          </>
        }
      />

      {inv.status === "void" && (
        <div role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
          Dibatalkan {formatTanggalWaktu(inv.voided_at)}. Alasan: {inv.void_reason}
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-3">
        <div className="min-w-0 space-y-5 xl:col-span-2">
          {inv.editable ? <InvoiceForm invoice={inv} onSaved={saved} /> : <InvoiceLines invoice={inv} />}
          <Card title="Pembayaran">
            {inv.allocations.length === 0 ? (
              <p className="text-sm text-muted">
                {inv.status === "issued" ? "Belum ada pembayaran tercatat." : "Pembayaran dicatat setelah invoice terbit."}
              </p>
            ) : (
              <ul className="divide-y divide-border text-sm">
                {inv.allocations.map((a) => (
                  <li key={a.payment_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                    <div>
                      <span className={`tabular font-medium ${a.payment_status === "void" ? "line-through text-muted" : ""}`}>
                        {formatMoney(a.amount, inv.currency)}
                      </span>{" "}
                      <span className="text-xs text-muted">
                        {formatTanggal(a.payment_date)} · {PAYMENT_METHOD[a.method]}
                        {a.reference && ` · ${a.reference}`}
                      </span>
                    </div>
                    {a.payment_status === "void" ? (
                      <StatusBadge tone="danger">Dibatalkan</StatusBadge>
                    ) : (
                      canWrite && (
                        <Button size="sm" variant="ghost" onClick={() => setVoidingPayment(a.payment_id)}>
                          Batalkan
                        </Button>
                      )
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <aside className="space-y-5">
          <Card title="Ringkasan">
            <dl className="space-y-1 text-sm">
              <Row label="Subtotal" value={formatMoney(inv.subtotal, inv.currency)} />
              {inv.tax_label && (
                <Row label={`${inv.tax_label} ${formatPercent(inv.tax_rate_percent)}`} value={formatMoney(inv.tax_amount, inv.currency)} />
              )}
              <Row label="Total tagihan" value={formatMoney(inv.grand_total, inv.currency)} strong />
              {inv.status === "issued" && (
                <>
                  <Row label="Sudah dibayar" value={formatMoney(inv.amount_paid, inv.currency)} />
                  <Row label="Sisa tagihan" value={formatMoney(inv.outstanding, inv.currency)} strong />
                </>
              )}
            </dl>
            <dl className="space-y-1 border-t border-border pt-2 text-xs text-muted">
              <div>Klien: {inv.client.name}</div>
              <div>
                Proyek: {inv.project.number} — {inv.project.name}
              </div>
              <div>Tanggal terbit: {inv.issue_date ? formatTanggal(inv.issue_date) : "—"}</div>
              <div>Jatuh tempo: {inv.due_date ? formatTanggal(inv.due_date) : "—"}</div>
            </dl>
          </Card>
          <ApprovalTimeline approvals={inv.approvals} />
        </aside>
      </div>

      {canAudit && (
        <Card title="Aktivitas">
          <AuditList entityType="invoice" entityId={inv.id} />
        </Card>
      )}

      <IssueDocumentDialog
        open={issuing}
        endpoint={`/invoices/${id}/issue`}
        title="Terbitkan invoice"
        summary={
          <p>
            Invoice senilai <strong className="tabular">{formatMoney(inv.grand_total, inv.currency)}</strong> untuk{" "}
            <strong>{inv.client.name}</strong> mendapat nomor dan tanggal terbit hari ini; jatuh tempo{" "}
            {inv.due_date ? formatTanggal(inv.due_date) : "—"}.
          </p>
        }
        onClose={() => setIssuing(false)}
        onIssued={(document) => {
          refresh();
          void queryClient.invalidateQueries({ queryKey: ["documents"] });
          toast.success(`Invoice ${document.number} diterbitkan.`);
        }}
      />
      <RecordPaymentDialog
        invoice={paying ? inv : null}
        onClose={() => setPaying(false)}
        onRecorded={(payment: Payment) => {
          refresh();
          toast.success(`Pembayaran ${formatMoney(payment.amount, payment.currency)} dicatat.`);
        }}
      />
      <VoidDocumentDialog
        number={voiding ? inv.number : null}
        title="Batalkan invoice"
        confirmLabel="Batalkan invoice"
        message={
          <>
            Invoice <strong>{inv.number}</strong> dan dokumennya ditandai <strong>dibatalkan</strong>. Termin
            terkait dapat ditagih ulang dengan invoice baru.
          </>
        }
        onClose={() => setVoiding(false)}
        onConfirm={async (reason) => saved(await api.post<Invoice>(`/invoices/${id}/void`, { reason }))}
      />
      <VoidDocumentDialog
        number={voidingPayment}
        title="Batalkan pembayaran"
        confirmLabel="Batalkan pembayaran"
        message="Pembayaran ini dibatalkan dan seluruh alokasinya dilepas; sisa tagihan bertambah kembali."
        onClose={() => setVoidingPayment(null)}
        onConfirm={async (reason) => {
          await api.post<Payment>(`/payments/${voidingPayment}/void`, { reason });
          refresh();
        }}
      />
      <ConfirmDialog
        open={deleting}
        title="Hapus invoice?"
        message="Invoice yang belum terbit ini akan dihapus."
        confirmLabel="Hapus"
        danger
        onConfirm={async () => {
          try {
            await api.delete(`/invoices/${id}`);
            void queryClient.invalidateQueries({ queryKey: ["invoices"] });
            router.replace("/invoice");
          } catch (error) {
            toast.error(errorMessage(error));
            setDeleting(false);
          }
        }}
        onClose={() => setDeleting(false)}
      />
    </div>
  );
}

const lineSchema = z.object({
  description: z.string().trim().min(1, "Uraian wajib diisi.").max(500),
  quantity: decimalString({ integerDigits: 14, fractionDigits: 4, positive: true, label: "Volume" }).refine((v) => v !== "", "Wajib."),
  unit: z.string().trim().min(1, "Wajib.").max(32),
  unit_price: decimalString({ integerDigits: 16, fractionDigits: 4, label: "Harga" }).refine((v) => v !== "", "Wajib."),
});

export const invoiceFormSchema = z
  .object({
    title: z.string().trim().min(1, "Judul wajib diisi.").max(300),
    due_date: z.string(),
    notes: optionalText(10_000),
    tax_label: optionalText(32),
    tax_rate_percent: percentString,
    items: z.array(lineSchema).max(200),
  })
  .refine((v) => Boolean(v.tax_label.trim()) === Boolean(v.tax_rate_percent.trim()), {
    path: ["tax_rate_percent"],
    message: "Label dan tarif pajak diisi bersamaan.",
  });
export type InvoiceFormValues = z.infer<typeof invoiceFormSchema>;

function trimZeros(value: string): string {
  return value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
}

/** PATCH body; lines and tax are only sent for manual invoices (term invoices follow the schedule). */
export function invoicePayload(invoice: Pick<Invoice, "version" | "lines_editable" | "tax_label" | "tax_rate_percent">, values: InvoiceFormValues) {
  const base = blankToNull({ title: values.title, due_date: values.due_date, notes: values.notes });
  if (!invoice.lines_editable) {
    return { ...base, version: invoice.version, tax_label: invoice.tax_label, tax_rate_percent: invoice.tax_rate_percent };
  }
  return {
    ...base,
    version: invoice.version,
    tax_label: values.tax_label.trim() || null,
    tax_rate_percent: values.tax_rate_percent.trim() || null,
    items: values.items.map((i) => ({ ...i, description: i.description.trim(), unit: i.unit.trim() })),
  };
}

function InvoiceForm({ invoice, onSaved }: { invoice: Invoice; onSaved: (inv: Invoice) => void }) {
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    control,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<InvoiceFormValues>({
    resolver: zodResolver(invoiceFormSchema),
    values: {
      title: invoice.title,
      due_date: invoice.due_date ?? "",
      notes: invoice.notes ?? "",
      tax_label: invoice.tax_label ?? "",
      tax_rate_percent: invoice.tax_rate_percent ? trimZeros(invoice.tax_rate_percent) : "",
      items: invoice.items.map((i) => ({
        description: i.description,
        quantity: trimZeros(i.quantity),
        unit: i.unit,
        unit_price: trimZeros(i.unit_price),
      })),
    },
  });
  const lines = useFieldArray({ control, name: "items" });
  const editableLines = invoice.lines_editable;

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      onSaved(await api.patch<Invoice>(`/invoices/${invoice.id}`, invoicePayload(invoice, values)));
      toast.success("Invoice disimpan; total dihitung server.");
    } catch (error) {
      setFormError(applyServerErrors(error, setError, ["title", "due_date", "notes", "tax_label", "tax_rate_percent"]));
    }
  });

  return (
    <Card title={editableLines ? "Isi invoice" : "Isi invoice (nilai mengikuti termin)"}>
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={formError} />
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Judul" error={errors.title?.message} required className="sm:col-span-2">
            {(a) => <Input {...a} {...register("title")} />}
          </Field>
          <Field label="Jatuh tempo" error={errors.due_date?.message}>
            {(a) => <Input type="date" {...a} {...register("due_date")} />}
          </Field>
          {editableLines && (
            <>
              <Field label="Label pajak" error={errors.tax_label?.message} hint="Kosongkan bila tidak dikenakan.">
                {(a) => <Input placeholder="PPN" {...a} {...register("tax_label")} />}
              </Field>
              <Field label="Tarif pajak (%)" error={errors.tax_rate_percent?.message}>
                {(a) => <Input inputMode="decimal" {...a} {...register("tax_rate_percent")} />}
              </Field>
            </>
          )}
        </div>
        {editableLines ? (
          <div className="space-y-2">
            <p className="text-sm font-medium">Baris tagihan</p>
            {lines.fields.map((field, index) => (
              <fieldset key={field.id} className="grid gap-2 rounded-md border border-border p-2 sm:grid-cols-12" aria-label={`Baris ${index + 1}`}>
                <Input aria-label={`Uraian baris ${index + 1}`} className="sm:col-span-5" {...register(`items.${index}.description`)} />
                <Input aria-label={`Volume baris ${index + 1}`} className="tabular sm:col-span-2" inputMode="decimal" {...register(`items.${index}.quantity`)} />
                <Input aria-label={`Satuan baris ${index + 1}`} className="sm:col-span-1" {...register(`items.${index}.unit`)} />
                <Input aria-label={`Harga baris ${index + 1}`} className="tabular sm:col-span-3" inputMode="decimal" {...register(`items.${index}.unit_price`)} />
                <Button variant="ghost" size="sm" aria-label={`Hapus baris ${index + 1}`} onClick={() => lines.remove(index)}>
                  <Trash2 className="size-4" />
                </Button>
                {errors.items?.[index] && (
                  <p className="text-xs text-danger sm:col-span-12">
                    {Object.values(errors.items[index] ?? {})
                      .map((e) => (e as { message?: string }).message)
                      .filter(Boolean)
                      .join(" ")}
                  </p>
                )}
              </fieldset>
            ))}
            <Button size="sm" variant="secondary" onClick={() => lines.append({ description: "", quantity: "1", unit: "ls", unit_price: "" })}>
              <Plus aria-hidden className="size-4" />
              Tambah baris
            </Button>
          </div>
        ) : (
          <InvoiceLines invoice={invoice} bare />
        )}
        <Field label="Catatan" error={errors.notes?.message}>
          {(a) => <Textarea rows={2} {...a} {...register("notes")} />}
        </Field>
        <div className="flex items-center justify-between">
          <p className="text-xs text-muted">Jumlah per baris dan total dihitung server setelah disimpan.</p>
          <Button type="submit" size="sm" loading={isSubmitting} disabled={!isDirty}>
            Simpan
          </Button>
        </div>
      </form>
    </Card>
  );
}

function InvoiceLines({ invoice, bare = false }: { invoice: Invoice; bare?: boolean }) {
  const table = (
    <table className="w-full text-sm" aria-label="Baris invoice">
      <thead className="text-left text-xs text-muted">
        <tr>
          <th className="py-1 pr-2">Uraian</th>
          <th className="py-1 pr-2 text-right">Volume</th>
          <th className="py-1 pr-2 text-right">Harga</th>
          <th className="py-1 text-right">Jumlah</th>
        </tr>
      </thead>
      <tbody>
        {invoice.items.map((i) => (
          <tr key={i.id} className="border-t border-border">
            <td className="py-1.5 pr-2">{i.description}</td>
            <td className="py-1.5 pr-2 text-right tabular whitespace-nowrap">
              {formatQuantity(i.quantity)} {i.unit}
            </td>
            <td className="py-1.5 pr-2 text-right tabular whitespace-nowrap">{formatUnitPrice(i.unit_price, invoice.currency)}</td>
            <td className="py-1.5 text-right tabular whitespace-nowrap">{formatMoney(i.amount, invoice.currency)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
  if (bare) return table;
  return (
    <Card title="Isi invoice">
      {table}
      {invoice.notes && <p className="text-sm whitespace-pre-wrap text-muted">{invoice.notes}</p>}
    </Card>
  );
}

function BackLink() {
  return (
    <Link href="/invoice" className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground">
      <ArrowLeft aria-hidden className="size-4" />
      Kembali ke daftar invoice
    </Link>
  );
}

function Row({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={`flex justify-between gap-4 ${strong ? "font-semibold" : ""}`}>
      <dt>{label}</dt>
      <dd className="tabular">{value}</dd>
    </div>
  );
}
