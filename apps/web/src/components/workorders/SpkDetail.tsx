"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Ban, ClipboardList, Eye, Stamp, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { AuditList } from "@/components/audit/AuditList";
import { ApprovalTimeline, WorkflowButtons } from "@/components/billing/DocWorkflow";
import { IssueDocumentDialog } from "@/components/documents/IssueDocumentDialog";
import { VoidDocumentDialog } from "@/components/documents/VoidDocumentDialog";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog, Dialog } from "@/components/ui/Dialog";
import { Field, FormError, Input, Select, Textarea } from "@/components/ui/Field";
import { FullPageMessage } from "@/components/ui/FullPageMessage";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { API_BASE, ApiError, api, errorMessage, queryString } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { formatMoney, formatPercent, formatQuantity, formatTanggal, formatTanggalWaktu } from "@/lib/format";
import { applyServerErrors, blankToNull, optionalText } from "@/lib/forms";
import { BAST_KIND, DOC_STATUS, PAYMENT_STATE, options } from "@/lib/labels";
import type { Bast, BastKind, BastListItem, Page, Spk, SpkProgress } from "@/lib/types";

const LINK =
  "inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 text-xs font-medium hover:bg-surface-muted";

export function SpkDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const canAudit = useCan("audit.read");
  const queryKey = ["spk", "detail", id];
  const [issuing, setIssuing] = useState(false);
  const [voiding, setVoiding] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [creatingBast, setCreatingBast] = useState(false);

  const detail = useQuery({
    queryKey,
    queryFn: ({ signal }) => api.get<Spk>(`/spk/${id}`, { signal }),
    retry: false,
  });

  if (detail.isPending) return <FullPageMessage loading title="Memuat SPK…" />;
  if (detail.isError) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <div className="space-y-4">
        <BackLink />
        <PageHeader title={notFound ? "SPK tidak ditemukan" : "SPK gagal dimuat"} description={errorMessage(detail.error)} />
      </div>
    );
  }

  const spk = detail.data;
  const saved = (updated: Spk) => {
    queryClient.setQueryData(queryKey, updated);
    void queryClient.invalidateQueries({ queryKey: ["spk", "list"] });
    void queryClient.invalidateQueries({ queryKey: ["audit"] });
  };

  return (
    <div className="space-y-6">
      <BackLink />
      <PageHeader
        title={spk.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs">{spk.number ?? "SPK (belum bernomor)"}</span>
            <StatusBadge tone={DOC_STATUS[spk.status].tone}>{DOC_STATUS[spk.status].label}</StatusBadge>
            <Link href={`/penawaran/${spk.quotation.id}`} className="text-primary hover:underline">
              Penawaran {spk.quotation.number}
            </Link>
          </span>
        }
        actions={
          <>
            <a href={`${API_BASE}/spk/${id}/preview.pdf`} target="_blank" rel="noopener" className={LINK}>
              <Eye aria-hidden className="size-3.5" />
              Pratinjau PDF
            </a>
            <WorkflowButtons<Spk> base={`/spk/${id}`} actions={spk.allowed_actions} onDone={saved} />
            {spk.can_issue && (
              <Button size="sm" onClick={() => setIssuing(true)}>
                <Stamp aria-hidden className="size-4" />
                Terbitkan
              </Button>
            )}
            {spk.can_create_bast && (
              <Button size="sm" variant="secondary" onClick={() => setCreatingBast(true)}>
                <ClipboardList aria-hidden className="size-4" />
                Buat BAST
              </Button>
            )}
            {spk.can_void && (
              <Button size="sm" variant="secondary" onClick={() => setVoiding(true)}>
                <Ban aria-hidden className="size-4" />
                Batalkan
              </Button>
            )}
            {spk.can_delete && (
              <Button size="sm" variant="secondary" onClick={() => setDeleting(true)}>
                <Trash2 aria-hidden className="size-4" />
                Hapus
              </Button>
            )}
          </>
        }
      />

      {spk.status === "void" && (
        <div role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
          Dibatalkan {formatTanggalWaktu(spk.voided_at)}. Alasan: {spk.void_reason}
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-3">
        <div className="min-w-0 space-y-5 xl:col-span-2">
          {spk.editable ? <SpkForm spk={spk} onSaved={saved} /> : <SpkText spk={spk} />}
          <ContractProgress spk={spk} />
          {spk.status === "issued" && <SpkBastList spkId={spk.id} />}
          <Card title="Jadwal pembayaran (dari penawaran)">
            <TermsSummary spk={spk} />
          </Card>
        </div>
        <aside className="space-y-5">
          <Card title="Nilai kontrak">
            <dl className="space-y-1 text-sm">
              <Row label="Sebelum pajak (DPP)" value={formatMoney(spk.taxable_base, spk.currency)} />
              {spk.tax_label && (
                <Row label={`${spk.tax_label} ${formatPercent(spk.tax_rate_percent)}`} value={formatMoney(spk.tax_amount, spk.currency)} />
              )}
              <Row label="Nilai kontrak" value={formatMoney(spk.contract_value, spk.currency)} strong />
            </dl>
            <p className="text-xs text-muted">
              Disalin dari penawaran {spk.quotation.number} ({spk.rab.number} v{spk.rab_version_no}) dan tidak dapat diubah di sini.
            </p>
          </Card>
          <Card title="Para pihak">
            <div className="space-y-3 text-sm">
              <Party role="Pemberi kerja" party={spk.client.name} name={spk.client_signatory_name} title={spk.client_signatory_title} />
              <Party role="Pelaksana" party={null} name={spk.company_signatory_name} title={spk.company_signatory_title} />
              <p className="text-xs text-muted">
                Nama penanda tangan diisi pengguna dan dicetak di bawah ruang tanda tangan. Aplikasi tidak membuat tanda
                tangan atau stempel.
              </p>
            </div>
          </Card>
          <ApprovalTimeline approvals={spk.approvals} />
        </aside>
      </div>

      {canAudit && (
        <Card title="Aktivitas">
          <AuditList entityType="spk" entityId={spk.id} />
        </Card>
      )}

      <IssueDocumentDialog
        open={issuing}
        endpoint={`/spk/${id}/issue`}
        title="Terbitkan SPK"
        summary={
          <p>
            SPK <strong>{spk.title}</strong> senilai{" "}
            <strong className="tabular">{formatMoney(spk.contract_value, spk.currency)}</strong> akan diberi nomor dan diterbitkan
            sebagai PDF.
          </p>
        }
        onClose={() => setIssuing(false)}
        onIssued={(document) => {
          void detail.refetch();
          void queryClient.invalidateQueries({ queryKey: ["documents"] });
          void queryClient.invalidateQueries({ queryKey: ["spk", "list"] });
          toast.success(`SPK ${document.number} diterbitkan.`);
        }}
      />
      <VoidDocumentDialog
        number={voiding ? spk.number : null}
        title="Batalkan SPK"
        confirmLabel="Batalkan SPK"
        message={
          <>
            SPK <strong>{spk.number}</strong> dan dokumennya ditandai <strong>dibatalkan</strong>. Berkas tetap tersimpan
            sebagai arsip; penawaran dapat dibuatkan SPK baru.
          </>
        }
        onClose={() => setVoiding(false)}
        onConfirm={async (reason) => saved(await api.post<Spk>(`/spk/${id}/void`, { reason }))}
      />
      <ConfirmDialog
        open={deleting}
        title="Hapus SPK?"
        message={<>SPK “{spk.title}” (belum terbit) akan dihapus.</>}
        confirmLabel="Hapus"
        danger
        onConfirm={async () => {
          try {
            await api.delete(`/spk/${id}`);
            void queryClient.invalidateQueries({ queryKey: ["spk"] });
            router.replace("/spk-bast");
          } catch (error) {
            toast.error(errorMessage(error));
            setDeleting(false);
          }
        }}
        onClose={() => setDeleting(false)}
      />
      <CreateBastDialog
        spk={creatingBast ? spk : null}
        onClose={() => setCreatingBast(false)}
        onCreated={(bast) => {
          void queryClient.invalidateQueries({ queryKey: ["bast"] });
          router.push(`/spk-bast/bast/${bast.id}`);
        }}
      />
    </div>
  );
}

// --------------------------------------------------------------------------- form

export const spkFormSchema = z
  .object({
    title: z.string().trim().min(1, "Judul wajib diisi.").max(300),
    start_date: z.string(),
    end_date: z.string(),
    location: optionalText(300),
    scope: optionalText(10_000),
    terms: optionalText(10_000),
    notes: optionalText(10_000),
    client_signatory_name: optionalText(200),
    client_signatory_title: optionalText(200),
    company_signatory_name: optionalText(200),
    company_signatory_title: optionalText(200),
  })
  .refine((v) => !v.start_date || !v.end_date || v.end_date >= v.start_date, {
    path: ["end_date"],
    message: "Tanggal selesai tidak boleh sebelum tanggal mulai.",
  });
export type SpkFormValues = z.infer<typeof spkFormSchema>;
const SPK_FIELDS = Object.keys(spkFormSchema.shape);

export function spkPayload(spk: Pick<Spk, "version">, values: SpkFormValues) {
  return { ...blankToNull(values), version: spk.version };
}

function SpkForm({ spk, onSaved }: { spk: Spk; onSaved: (s: Spk) => void }) {
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<SpkFormValues>({
    resolver: zodResolver(spkFormSchema),
    values: {
      title: spk.title,
      start_date: spk.start_date ?? "",
      end_date: spk.end_date ?? "",
      location: spk.location ?? "",
      scope: spk.scope ?? "",
      terms: spk.terms ?? "",
      notes: spk.notes ?? "",
      client_signatory_name: spk.client_signatory_name ?? "",
      client_signatory_title: spk.client_signatory_title ?? "",
      company_signatory_name: spk.company_signatory_name ?? "",
      company_signatory_title: spk.company_signatory_title ?? "",
    },
  });
  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      onSaved(await api.patch<Spk>(`/spk/${spk.id}`, spkPayload(spk, values)));
      toast.success("SPK disimpan.");
    } catch (error) {
      setFormError(applyServerErrors(error, setError, SPK_FIELDS));
    }
  });
  return (
    <Card title="Isi SPK">
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={formError} />
        <p className="text-xs text-muted">
          Untuk diajukan, isi tanggal mulai, lingkup pekerjaan, dan nama penanda tangan kedua pihak.
        </p>
        <Field label="Judul pekerjaan" error={errors.title?.message} required>
          {(a) => <Input {...a} {...register("title")} />}
        </Field>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Tanggal mulai" error={errors.start_date?.message}>
            {(a) => <Input type="date" {...a} {...register("start_date")} />}
          </Field>
          <Field label="Tanggal selesai" error={errors.end_date?.message}>
            {(a) => <Input type="date" {...a} {...register("end_date")} />}
          </Field>
          <Field label="Lokasi" error={errors.location?.message}>
            {(a) => <Input {...a} {...register("location")} />}
          </Field>
        </div>
        <Field label="Lingkup pekerjaan" error={errors.scope?.message} hint="Disalin dari penawaran; sesuaikan bila perlu.">
          {(a) => <Textarea rows={3} {...a} {...register("scope")} />}
        </Field>
        <Field
          label="Ketentuan"
          error={errors.terms?.message}
          hint="Diisi dari template SPK. Aplikasi tidak menambahkan klausul hukum — tulis hanya ketentuan yang sudah disepakati."
        >
          {(a) => <Textarea rows={3} {...a} {...register("terms")} />}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Penanda tangan pemberi kerja" error={errors.client_signatory_name?.message}>
            {(a) => <Input {...a} {...register("client_signatory_name")} />}
          </Field>
          <Field label="Jabatan pemberi kerja" error={errors.client_signatory_title?.message}>
            {(a) => <Input {...a} {...register("client_signatory_title")} />}
          </Field>
          <Field label="Penanda tangan pelaksana" error={errors.company_signatory_name?.message}>
            {(a) => <Input {...a} {...register("company_signatory_name")} />}
          </Field>
          <Field label="Jabatan pelaksana" error={errors.company_signatory_title?.message}>
            {(a) => <Input {...a} {...register("company_signatory_title")} />}
          </Field>
        </div>
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

function SpkText({ spk }: { spk: Spk }) {
  const sections: [string, string | null][] = [
    ["Lingkup pekerjaan", spk.scope],
    ["Ketentuan", spk.terms],
    ["Catatan", spk.notes],
  ];
  return (
    <Card title="Isi SPK">
      <dl className="grid gap-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs text-muted">Tanggal SPK</dt>
          <dd>{spk.issue_date ? formatTanggal(spk.issue_date) : "Belum terbit"}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Jangka waktu</dt>
          <dd>
            {spk.start_date ? formatTanggal(spk.start_date) : "—"}
            {spk.end_date && ` s.d. ${formatTanggal(spk.end_date)}`}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Lokasi</dt>
          <dd>{spk.location ?? "—"}</dd>
        </div>
      </dl>
      {sections.map(
        ([title, text]) =>
          text && (
            <div key={title} className="text-sm">
              <p className="text-xs text-muted">{title}</p>
              <p className="whitespace-pre-wrap">{text}</p>
            </div>
          ),
      )}
    </Card>
  );
}

// --------------------------------------------------------------------------- contract & BAST

function ContractProgress({ spk }: { spk: Spk }) {
  const progress = useQuery({
    queryKey: ["spk", "progress", spk.id],
    queryFn: ({ signal }) => api.get<SpkProgress>(`/spk/${spk.id}/progress`, { signal }),
  });
  const issued = spk.status === "issued" || spk.status === "void";
  return (
    <Card title={issued ? "Volume kontrak & serah terima" : "Rincian volume pekerjaan"}>
      {progress.isPending && <p className="text-sm text-muted">Memuat…</p>}
      {progress.isError && <p className="text-sm text-danger">{errorMessage(progress.error)}</p>}
      {progress.data && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm" aria-label="Volume kontrak">
            <thead className="text-left text-xs text-muted">
              <tr>
                <th className="py-1 pr-2">No</th>
                <th className="py-1 pr-2">Uraian</th>
                <th className="py-1 pr-2 text-right">Kontrak</th>
                {issued && (
                  <>
                    <th className="py-1 pr-2 text-right">Diserahkan</th>
                    <th className="py-1 pr-2 text-right">Dalam proses</th>
                    <th className="py-1 text-right">Sisa</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {progress.data.items.map((row) => (
                <tr key={row.rab_item_id} className="border-t border-border">
                  <td className="py-1.5 pr-2 text-xs text-muted">{row.no}</td>
                  <td className="py-1.5 pr-2">
                    {row.name}
                    {row.code && <span className="ml-1 font-mono text-xs text-muted">{row.code}</span>}
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular whitespace-nowrap">
                    {formatQuantity(row.contract_quantity)} {row.unit}
                  </td>
                  {issued && (
                    <>
                      <td className="py-1.5 pr-2 text-right tabular">{formatQuantity(row.delivered_quantity)}</td>
                      <td className="py-1.5 pr-2 text-right tabular text-muted">{formatQuantity(row.pending_quantity)}</td>
                      <td className="py-1.5 text-right font-medium tabular">{formatQuantity(row.remaining_quantity)}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {issued && (
            <p className="mt-2 text-xs text-muted">
              “Diserahkan” hanya menghitung BAST yang sudah terbit; “Dalam proses” adalah BAST draft/review/disetujui.
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

function SpkBastList({ spkId }: { spkId: string }) {
  const list = useQuery({
    queryKey: ["bast", "list", { spk_id: spkId }],
    queryFn: ({ signal }) => api.get<Page<BastListItem>>(`/bast${queryString({ spk_id: spkId, page_size: 100 })}`, { signal }),
  });
  return (
    <Card title="BAST untuk SPK ini">
      {list.isPending && <p className="text-sm text-muted">Memuat…</p>}
      {list.isError && <p className="text-sm text-danger">{errorMessage(list.error)}</p>}
      {list.data && list.data.items.length === 0 && <p className="text-sm text-muted">Belum ada BAST.</p>}
      {list.data && list.data.items.length > 0 && (
        <ul className="divide-y divide-border text-sm">
          {list.data.items.map((b) => (
            <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>
                <Link href={`/spk-bast/bast/${b.id}`} className="font-mono text-xs font-medium text-primary hover:underline">
                  {b.number ?? "Draft"}
                </Link>{" "}
                {b.title}
                <span className="block text-xs text-muted">
                  {BAST_KIND[b.kind]} · {b.handover_date ? formatTanggal(b.handover_date) : "tanggal belum diisi"}
                </span>
              </span>
              <StatusBadge tone={DOC_STATUS[b.status].tone}>{DOC_STATUS[b.status].label}</StatusBadge>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function TermsSummary({ spk }: { spk: Spk }) {
  if (spk.payment_terms.length === 0) return <p className="text-sm text-muted">Penawaran tidak memiliki jadwal pembayaran.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[480px] text-sm" aria-label="Jadwal pembayaran">
        <thead className="text-left text-xs text-muted">
          <tr>
            <th className="py-1 pr-2">Termin</th>
            <th className="py-1 pr-2 text-right">Total</th>
            <th className="py-1 pr-2">Jatuh tempo</th>
            <th className="py-1">Invoice</th>
          </tr>
        </thead>
        <tbody>
          {spk.payment_terms.map((t) => (
            <tr key={t.id} className="border-t border-border align-top">
              <td className="py-1.5 pr-2">
                {t.name}
                {t.percent && <span className="text-xs text-muted"> ({formatPercent(t.percent)})</span>}
              </td>
              <td className="py-1.5 pr-2 text-right tabular whitespace-nowrap">{formatMoney(t.total_amount, spk.currency)}</td>
              <td className="py-1.5 pr-2 whitespace-nowrap">{t.due_date ? formatTanggal(t.due_date) : "—"}</td>
              <td className="py-1.5 text-xs">
                {t.invoice ? (
                  <Link href={`/invoice/${t.invoice.id}`} className="text-primary hover:underline">
                    {t.invoice.number ?? "Draft"}
                    {t.invoice.payment_state && ` · ${PAYMENT_STATE[t.invoice.payment_state].label}`}
                  </Link>
                ) : (
                  <span className="text-muted">Belum ditagih</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CreateBastDialog({
  spk,
  onClose,
  onCreated,
}: {
  spk: Spk | null;
  onClose: () => void;
  onCreated: (bast: Bast) => void;
}) {
  return (
    <Dialog open={spk !== null} onClose={onClose} title="Buat BAST">
      {spk && <CreateBastForm spk={spk} onClose={onClose} onCreated={onCreated} />}
    </Dialog>
  );
}

function CreateBastForm({ spk, onClose, onCreated }: { spk: Spk; onClose: () => void; onCreated: (bast: Bast) => void }) {
  const progress = useQuery({
    queryKey: ["spk", "progress", spk.id],
    queryFn: ({ signal }) => api.get<SpkProgress>(`/spk/${spk.id}/progress`, { signal }),
  });
  const hasFinal = Boolean(progress.data?.final_bast);
  const [kind, setKind] = useState<BastKind>("partial");
  const [title, setTitle] = useState("");
  const [prefill, setPrefill] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      onCreated(
        await api.post<Bast>("/bast", { spk_id: spk.id, kind, title: title.trim() || null, prefill_remaining: prefill }),
      );
      onClose();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <FormError message={error} />
      <Field label="Jenis serah terima" required>
        {(a) => (
          <Select {...a} value={kind} onChange={(e) => setKind(e.target.value as BastKind)}>
            {options(BAST_KIND).map((o) => (
              <option key={o.value} value={o.value} disabled={o.value === "final" && hasFinal}>
                {o.label}
                {o.value === "final" && hasFinal ? " (sudah ada)" : ""}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="Judul" hint="Kosongkan untuk judul otomatis dari jenis dan nama pekerjaan.">
        {(a) => <Input {...a} maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} />}
      </Field>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5" checked={prefill} onChange={(e) => setPrefill(e.target.checked)} />
        <span>
          Isi baris dengan sisa volume kontrak
          <span className="block text-xs text-muted">
            Hanya titik awal — ubah atau hapus baris agar sesuai dengan yang benar-benar diserahkan.
          </span>
        </span>
      </label>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Batal
        </Button>
        <Button loading={busy} onClick={() => void create()}>
          Buat draft BAST
        </Button>
      </div>
    </div>
  );
}

function Party({ role, party, name, title }: { role: string; party: string | null; name: string | null; title: string | null }) {
  return (
    <div>
      <p className="text-xs text-muted">{role}</p>
      {party && <p className="font-medium">{party}</p>}
      <p>
        {name ?? <span className="text-muted">Nama penanda tangan belum diisi</span>}
        {title && <span className="text-muted"> — {title}</span>}
      </p>
    </div>
  );
}

function BackLink() {
  return (
    <Link href="/spk-bast" className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground">
      <ArrowLeft aria-hidden className="size-4" />
      Kembali ke daftar SPK & BAST
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
