"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Ban, Check, Handshake, Receipt, Stamp, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { AuditList } from "@/components/audit/AuditList";
import { IssueDocumentDialog } from "@/components/documents/IssueDocumentDialog";
import { PdfPreviewButton } from "@/components/documents/PdfPreview";
import { VoidDocumentDialog } from "@/components/documents/VoidDocumentDialog";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { Field, FormError, Input, Textarea } from "@/components/ui/Field";
import { FullPageMessage } from "@/components/ui/FullPageMessage";
import { KeyFigure } from "@/components/ui/KeyFigure";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { API_BASE, ApiError, api, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { formatMoney, formatPercent, formatTanggal, formatTanggalWaktu } from "@/lib/format";
import { applyServerErrors, blankToNull, optionalText } from "@/lib/forms";
import { CLIENT_RESPONSE, DOC_STATUS, PAYMENT_STATE } from "@/lib/labels";
import type { ClientResponse, Invoice, Quotation, Spk } from "@/lib/types";
import { ApprovalTimeline, WorkflowButtons } from "./DocWorkflow";
import { TermsEditor, rowsFrom } from "./TermsEditor";

export function QuotationDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const canAudit = useCan("audit.read");
  const queryKey = ["quotations", "detail", id];
  const [issuing, setIssuing] = useState(false);
  const [voiding, setVoiding] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [editingTerms, setEditingTerms] = useState(false);
  const [creatingSpk, setCreatingSpk] = useState(false);

  const detail = useQuery({
    queryKey,
    queryFn: ({ signal }) => api.get<Quotation>(`/quotations/${id}`, { signal }),
    retry: false,
  });

  if (detail.isPending) return <FullPageMessage loading title="Memuat penawaran…" />;
  if (detail.isError) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <div className="space-y-4">
        <BackLink />
        <PageHeader title={notFound ? "Penawaran tidak ditemukan" : "Penawaran gagal dimuat"} description={errorMessage(detail.error)} />
      </div>
    );
  }

  const q = detail.data;
  const saved = (updated: Quotation) => {
    queryClient.setQueryData(queryKey, updated);
    void queryClient.invalidateQueries({ queryKey: ["quotations", "list"] });
    void queryClient.invalidateQueries({ queryKey: ["audit"] });
  };
  const createSpk = async () => {
    setCreatingSpk(true);
    try {
      const spk = await api.post<Spk>("/spk", { quotation_id: id });
      void queryClient.invalidateQueries({ queryKey: ["spk"] });
      router.push(`/spk-bast/spk/${spk.id}`);
    } catch (error) {
      toast.error(errorMessage(error));
      setCreatingSpk(false);
    }
  };
  const respond = async (response: ClientResponse) => {
    try {
      saved(await api.post<Quotation>(`/quotations/${id}/response`, { response, note: null }));
      toast.success(`Tanggapan klien dicatat: ${CLIENT_RESPONSE[response].label}.`);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  };

  return (
    <div className="space-y-6">
      <BackLink />
      <PageHeader
        title={q.subject}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs">{q.number}</span>
            <StatusBadge tone={DOC_STATUS[q.status].tone}>{DOC_STATUS[q.status].label}</StatusBadge>
            {q.client_response && (
              <StatusBadge tone={CLIENT_RESPONSE[q.client_response].tone}>{CLIENT_RESPONSE[q.client_response].label}</StatusBadge>
            )}
            {q.expired && <StatusBadge tone="danger">Kedaluwarsa</StatusBadge>}
            <Link href={`/rab/${q.rab.id}?v=${q.rab_version_no}`} className="text-primary hover:underline">
              {q.rab.number} v{q.rab_version_no}
            </Link>
            {q.spk && (
              <Link href={`/spk-bast/spk/${q.spk.id}`} className="text-primary hover:underline">
                SPK {q.spk.number ?? "(draft)"} · {DOC_STATUS[q.spk.status].label}
              </Link>
            )}
          </span>
        }
        actions={
          <>
            <PdfPreviewButton url={`${API_BASE}/quotations/${id}/preview.pdf`} title={`Pratinjau ${q.number}`} />
            <WorkflowButtons<Quotation> base={`/quotations/${id}`} actions={q.allowed_actions} onDone={saved} />
            {q.can_issue && (
              <Button size="sm" onClick={() => setIssuing(true)}>
                <Stamp aria-hidden className="size-4" />
                Terbitkan
              </Button>
            )}
            {q.can_respond && (
              <>
                <Button size="sm" variant="secondary" onClick={() => void respond("accepted")}>
                  <Check aria-hidden className="size-4" />
                  Diterima klien
                </Button>
                <Button size="sm" variant="secondary" onClick={() => void respond("declined")}>
                  <X aria-hidden className="size-4" />
                  Ditolak klien
                </Button>
              </>
            )}
            {q.can_create_spk && (
              <Button size="sm" variant="secondary" loading={creatingSpk} onClick={() => void createSpk()}>
                <Handshake aria-hidden className="size-4" />
                Buat SPK
              </Button>
            )}
            {q.can_void && (
              <Button size="sm" variant="secondary" onClick={() => setVoiding(true)}>
                <Ban aria-hidden className="size-4" />
                Batalkan
              </Button>
            )}
            {q.can_delete && (
              <Button size="sm" variant="secondary" onClick={() => setDeleting(true)}>
                <Trash2 aria-hidden className="size-4" />
                Hapus
              </Button>
            )}
          </>
        }
      />

      {q.status === "void" && (
        <div role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
          Dibatalkan {formatTanggalWaktu(q.voided_at)}. Alasan: {q.void_reason}
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-3">
        <div className="min-w-0 space-y-5 xl:col-span-2">
          {q.editable ? <QuotationForm quotation={q} onSaved={saved} /> : <QuotationText quotation={q} />}
          <Card
            title="Jadwal pembayaran (termin)"
            actions={
              q.editable &&
              !editingTerms && (
                <Button size="sm" variant="secondary" onClick={() => setEditingTerms(true)}>
                  Ubah jadwal
                </Button>
              )
            }
          >
            {editingTerms || (q.editable && q.payment_terms.length === 0) ? (
              <TermsEditor
                initial={rowsFrom(q.payment_terms)}
                onCancel={q.payment_terms.length ? () => setEditingTerms(false) : undefined}
                onSave={async (terms) => {
                  saved(await api.put<Quotation>(`/quotations/${id}/terms`, { version: q.version, terms }));
                  setEditingTerms(false);
                  toast.success("Jadwal pembayaran disimpan.");
                }}
              />
            ) : (
              <TermsTable quotation={q} onInvoiced={(invoice) => router.push(`/invoice/${invoice.id}`)} />
            )}
          </Card>
        </div>
        <aside className="space-y-5">
          <Card title="Nilai penawaran">
            <dl className="space-y-1 text-sm">
              <Row label="Subtotal" value={formatMoney(q.subtotal, q.currency)} />
              {q.discount_amount !== "0.00" && <Row label="Diskon" value={`− ${formatMoney(q.discount_amount, q.currency)}`} />}
              <Row label="Sebelum pajak (DPP)" value={formatMoney(q.taxable_base, q.currency)} />
              {q.tax_label && (
                <Row label={`${q.tax_label} ${formatPercent(q.tax_rate_percent)}`} value={formatMoney(q.tax_amount, q.currency)} />
              )}
              <KeyFigure label="Total" value={formatMoney(q.grand_total, q.currency)} />
            </dl>
            <p className="text-xs text-muted">Nilai disalin dari RAB yang disetujui dan tidak dapat diubah di sini.</p>
          </Card>
          <Card title="Penerima">
            <p className="text-sm font-medium">{q.client?.name ?? "-"}</p>
            <p className="text-xs text-muted">
              {q.project.number} · {q.project.name}
            </p>
          </Card>
          <ApprovalTimeline approvals={q.approvals} />
        </aside>
      </div>

      {canAudit && (
        <Card title="Aktivitas">
          <AuditList entityType="quotation" entityId={q.id} />
        </Card>
      )}

      <IssueDocumentDialog
        open={issuing}
        endpoint={`/quotations/${id}/issue`}
        title="Terbitkan penawaran"
        summary={
          <p>
            Penawaran <strong>{q.number}</strong> senilai <strong className="tabular">{formatMoney(q.grand_total, q.currency)}</strong>{" "}
            dengan {q.payment_terms.length} termin akan diterbitkan sebagai PDF.
          </p>
        }
        onClose={() => setIssuing(false)}
        onIssued={(document) => {
          void detail.refetch();
          void queryClient.invalidateQueries({ queryKey: ["documents"] });
          toast.success(`Penawaran ${document.number} diterbitkan.`);
        }}
      />
      <VoidDocumentDialog
        number={voiding ? q.number : null}
        title="Batalkan penawaran"
        confirmLabel="Batalkan penawaran"
        message={
          <>
            Penawaran <strong>{q.number}</strong> dan dokumennya ditandai <strong>dibatalkan</strong>. Berkas
            tetap tersimpan sebagai arsip.
          </>
        }
        onClose={() => setVoiding(false)}
        onConfirm={async (reason) => saved(await api.post<Quotation>(`/quotations/${id}/void`, { reason }))}
      />
      <ConfirmDialog
        open={deleting}
        title="Hapus penawaran?"
        message={<>Penawaran {q.number} (belum terbit) akan dihapus.</>}
        confirmLabel="Hapus"
        danger
        onConfirm={async () => {
          try {
            await api.delete(`/quotations/${id}`);
            void queryClient.invalidateQueries({ queryKey: ["quotations"] });
            router.replace("/penawaran");
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

const formSchema = z.object({
  subject: z.string().trim().min(1, "Perihal wajib diisi.").max(300),
  valid_until: z.string(),
  introduction: optionalText(10_000),
  scope: optionalText(10_000),
  terms: optionalText(10_000),
  notes: optionalText(10_000),
});
type FormValues = z.infer<typeof formSchema>;

function QuotationForm({ quotation, onSaved }: { quotation: Quotation; onSaved: (q: Quotation) => void }) {
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    values: {
      subject: quotation.subject,
      valid_until: quotation.valid_until ?? "",
      introduction: quotation.introduction ?? "",
      scope: quotation.scope ?? "",
      terms: quotation.terms ?? "",
      notes: quotation.notes ?? "",
    },
  });
  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      onSaved(await api.patch<Quotation>(`/quotations/${quotation.id}`, { ...blankToNull(values), version: quotation.version }));
      toast.success("Penawaran disimpan.");
    } catch (error) {
      setFormError(applyServerErrors(error, setError, Object.keys(formSchema.shape)));
    }
  });
  return (
    <Card title="Isi penawaran">
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={formError} />
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Perihal" error={errors.subject?.message} required className="sm:col-span-2">
            {(a) => <Input {...a} {...register("subject")} />}
          </Field>
          <Field label="Berlaku sampai" error={errors.valid_until?.message}>
            {(a) => <Input type="date" {...a} {...register("valid_until")} />}
          </Field>
        </div>
        <Field label="Pembuka" error={errors.introduction?.message} hint="Kosongkan untuk kalimat pembuka standar yang netral.">
          {(a) => <Textarea rows={2} {...a} {...register("introduction")} />}
        </Field>
        <Field label="Lingkup pekerjaan" error={errors.scope?.message}>
          {(a) => <Textarea rows={3} {...a} {...register("scope")} />}
        </Field>
        <Field label="Ketentuan" error={errors.terms?.message} hint="Diisi dari template dokumen; aplikasi tidak menambahkan klausul hukum.">
          {(a) => <Textarea rows={3} {...a} {...register("terms")} />}
        </Field>
        <Field label="Catatan" error={errors.notes?.message}>
          {(a) => <Textarea rows={2} {...a} {...register("notes")} />}
        </Field>
        <div className="flex justify-end">
          <Button type="submit" size="sm" loading={isSubmitting} disabled={!isDirty}>
            Simpan
          </Button>
        </div>
      </form>
    </Card>
  );
}

function QuotationText({ quotation: q }: { quotation: Quotation }) {
  const sections: [string, string | null][] = [
    ["Pembuka", q.introduction],
    ["Lingkup pekerjaan", q.scope],
    ["Ketentuan", q.terms],
    ["Catatan", q.notes],
  ];
  return (
    <Card title="Isi penawaran">
      <p className="text-sm">Berlaku sampai: {q.valid_until ? formatTanggal(q.valid_until) : "-"}</p>
      {sections.map(
        ([title, text]) =>
          text && (
            <div key={title} className="text-sm">
              <p className="text-xs text-muted">{title}</p>
              <p className="whitespace-pre-wrap">{text}</p>
            </div>
          ),
      )}
      {q.response_note && <p className="text-xs text-muted">Catatan tanggapan klien: {q.response_note}</p>}
    </Card>
  );
}

function TermsTable({ quotation: q, onInvoiced }: { quotation: Quotation; onInvoiced: (invoice: Invoice) => void }) {
  const [creating, setCreating] = useState<string | null>(null);
  if (q.payment_terms.length === 0) return <p className="text-sm text-muted">Belum ada jadwal pembayaran.</p>;
  return (
    <div className="space-y-2 overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm" aria-label="Jadwal pembayaran">
        <thead className="text-left text-xs text-muted">
          <tr>
            <th className="py-1 pr-2">Termin</th>
            <th className="py-1 pr-2 text-right">Porsi</th>
            <th className="py-1 pr-2 text-right">Sebelum pajak</th>
            <th className="py-1 pr-2 text-right">Pajak</th>
            <th className="py-1 pr-2 text-right">Total</th>
            <th className="py-1 pr-2">Jatuh tempo</th>
            <th className="py-1">Invoice</th>
          </tr>
        </thead>
        <tbody>
          {q.payment_terms.map((t) => (
            <tr key={t.id} className="border-t border-border align-top">
              <td className="py-1.5 pr-2">
                <div className="font-medium">{t.name}</div>
                {t.description && <div className="text-xs text-muted">{t.description}</div>}
              </td>
              <td className="py-1.5 pr-2 text-right tabular">{t.percent ? formatPercent(t.percent) : "Nilai tetap"}</td>
              <td className="py-1.5 pr-2 text-right tabular whitespace-nowrap">{formatMoney(t.amount, q.currency)}</td>
              <td className="py-1.5 pr-2 text-right tabular whitespace-nowrap">{formatMoney(t.tax_amount, q.currency)}</td>
              <td className="py-1.5 pr-2 text-right font-medium tabular whitespace-nowrap">{formatMoney(t.total_amount, q.currency)}</td>
              <td className="py-1.5 pr-2 whitespace-nowrap">{t.due_date ? formatTanggal(t.due_date) : "-"}</td>
              <td className="py-1.5">
                {t.invoice ? (
                  <Link href={`/invoice/${t.invoice.id}`} className="text-xs text-primary hover:underline">
                    {t.invoice.number ?? "Draft"}
                    {t.invoice.payment_state ? ` · ${PAYMENT_STATE[t.invoice.payment_state].label}` : ` · ${DOC_STATUS[t.invoice.status].label}`}
                  </Link>
                ) : q.can_invoice ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={creating === t.id}
                    onClick={async () => {
                      setCreating(t.id);
                      try {
                        onInvoiced(await api.post<Invoice>(`/quotations/${q.id}/terms/${t.id}/invoice`));
                      } catch (error) {
                        toast.error(errorMessage(error));
                      } finally {
                        setCreating(null);
                      }
                    }}
                  >
                    <Receipt aria-hidden className="size-3.5" />
                    Buat invoice
                  </Button>
                ) : (
                  <span className="text-xs text-muted">-</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {q.status === "issued" && !q.client_response && (
        <p className="text-xs text-muted">Invoice termin dapat dibuat setelah penawaran dicatat diterima klien.</p>
      )}
    </div>
  );
}

function BackLink() {
  return (
    <Link href="/penawaran" className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground">
      <ArrowLeft aria-hidden className="size-4" />
      Kembali ke daftar penawaran
    </Link>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt>{label}</dt>
      <dd className="tabular">{value}</dd>
    </div>
  );
}
