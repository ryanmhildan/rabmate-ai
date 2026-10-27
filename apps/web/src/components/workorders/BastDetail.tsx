"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Ban, Plus, Stamp, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { type FieldPath, type UseFormSetError, useFieldArray, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { AuditList } from "@/components/audit/AuditList";
import { ApprovalTimeline, WorkflowButtons } from "@/components/billing/DocWorkflow";
import { IssueDocumentDialog } from "@/components/documents/IssueDocumentDialog";
import { PdfPreviewButton } from "@/components/documents/PdfPreview";
import { VoidDocumentDialog } from "@/components/documents/VoidDocumentDialog";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { Field, FormError, Input, Select, Textarea } from "@/components/ui/Field";
import { FullPageMessage } from "@/components/ui/FullPageMessage";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { API_BASE, ApiError, api, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { formatQuantity, formatTanggal, formatTanggalWaktu } from "@/lib/format";
import { applyServerErrors, blankToNull, decimalString, optionalText } from "@/lib/forms";
import { BAST_KIND, DOC_STATUS } from "@/lib/labels";
import type { Bast, ContractItemProgress, SpkProgress } from "@/lib/types";

export function BastDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const canAudit = useCan("audit.read");
  const queryKey = ["bast", "detail", id];
  const [issuing, setIssuing] = useState(false);
  const [voiding, setVoiding] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const detail = useQuery({
    queryKey,
    queryFn: ({ signal }) => api.get<Bast>(`/bast/${id}`, { signal }),
    retry: false,
  });
  const spkId = detail.data?.spk.id;
  const progress = useQuery({
    queryKey: ["spk", "progress", spkId],
    queryFn: ({ signal }) => api.get<SpkProgress>(`/spk/${spkId}/progress`, { signal }),
    enabled: Boolean(spkId),
  });

  if (detail.isPending) return <FullPageMessage loading title="Memuat BAST…" />;
  if (detail.isError) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <div className="space-y-4">
        <BackLink />
        <PageHeader title={notFound ? "BAST tidak ditemukan" : "BAST gagal dimuat"} description={errorMessage(detail.error)} />
      </div>
    );
  }

  const bast = detail.data;
  const contract = progress.data?.items ?? [];
  const saved = (updated: Bast) => {
    queryClient.setQueryData(queryKey, updated);
    void queryClient.invalidateQueries({ queryKey: ["bast", "list"] });
    void queryClient.invalidateQueries({ queryKey: ["spk", "progress", updated.spk.id] });
    void queryClient.invalidateQueries({ queryKey: ["audit"] });
  };

  return (
    <div className="space-y-6">
      <BackLink />
      <PageHeader
        title={bast.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs">{bast.number ?? "BAST (belum bernomor)"}</span>
            <StatusBadge tone={DOC_STATUS[bast.status].tone}>{DOC_STATUS[bast.status].label}</StatusBadge>
            <StatusBadge tone="neutral">{BAST_KIND[bast.kind]}</StatusBadge>
            <Link href={`/spk-bast/spk/${bast.spk.id}`} className="text-primary hover:underline">
              SPK {bast.spk.number}
            </Link>
          </span>
        }
        actions={
          <>
            <PdfPreviewButton
              url={`${API_BASE}/bast/${id}/preview.pdf`}
              title={`Pratinjau ${bast.number ?? "BAST"}`}
            />
            <WorkflowButtons<Bast> base={`/bast/${id}`} actions={bast.allowed_actions} onDone={saved} />
            {bast.can_issue && (
              <Button size="sm" onClick={() => setIssuing(true)}>
                <Stamp aria-hidden className="size-4" />
                Terbitkan
              </Button>
            )}
            {bast.can_void && (
              <Button size="sm" variant="secondary" onClick={() => setVoiding(true)}>
                <Ban aria-hidden className="size-4" />
                Batalkan
              </Button>
            )}
            {bast.can_delete && (
              <Button size="sm" variant="secondary" onClick={() => setDeleting(true)}>
                <Trash2 aria-hidden className="size-4" />
                Hapus
              </Button>
            )}
          </>
        }
      />

      {bast.status === "void" && (
        <div role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
          Dibatalkan {formatTanggalWaktu(bast.voided_at)}. Alasan: {bast.void_reason}
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-3">
        <div className="min-w-0 space-y-5 xl:col-span-2">
          {bast.editable ? (
            progress.isPending ? (
              <FullPageMessage loading title="Memuat volume kontrak…" />
            ) : (
              <BastForm bast={bast} contract={contract} onSaved={saved} />
            )
          ) : (
            <BastText bast={bast} contract={contract} />
          )}
        </div>
        <aside className="space-y-5">
          <Card title="Para pihak">
            <div className="space-y-3 text-sm">
              <Party role="Yang menyerahkan (pelaksana)" name={bast.delivered_by_name} title={bast.delivered_by_title} />
              <Party role={`Yang menerima (${bast.client.name})`} name={bast.received_by_name} title={bast.received_by_title} />
              <p className="text-xs text-muted">Nama diisi pengguna. Aplikasi tidak membuat tanda tangan atau stempel.</p>
            </div>
          </Card>
          <ApprovalTimeline approvals={bast.approvals} />
        </aside>
      </div>

      {canAudit && (
        <Card title="Aktivitas">
          <AuditList entityType="bast" entityId={bast.id} />
        </Card>
      )}

      <IssueDocumentDialog
        open={issuing}
        endpoint={`/bast/${id}/issue`}
        title="Terbitkan BAST"
        summary={
          <p>
            BAST <strong>{bast.title}</strong> ({bast.items.length} baris, serah terima{" "}
            {bast.handover_date ? formatTanggal(bast.handover_date) : "-"}) akan diberi nomor dan diterbitkan sebagai PDF.
            Volume diperiksa ulang terhadap kontrak saat terbit.
          </p>
        }
        onClose={() => setIssuing(false)}
        onIssued={(document) => {
          void detail.refetch();
          void queryClient.invalidateQueries({ queryKey: ["documents"] });
          void queryClient.invalidateQueries({ queryKey: ["bast", "list"] });
          void queryClient.invalidateQueries({ queryKey: ["spk"] });
          toast.success(`BAST ${document.number} diterbitkan.`);
        }}
      />
      <VoidDocumentDialog
        number={voiding ? bast.number : null}
        title="Batalkan BAST"
        confirmLabel="Batalkan BAST"
        message={
          <>
            BAST <strong>{bast.number}</strong> dan dokumennya ditandai <strong>dibatalkan</strong>; volumenya tidak lagi
            dihitung sebagai sudah diserahkan. Berkas tetap tersimpan sebagai arsip.
          </>
        }
        onClose={() => setVoiding(false)}
        onConfirm={async (reason) => saved(await api.post<Bast>(`/bast/${id}/void`, { reason }))}
      />
      <ConfirmDialog
        open={deleting}
        title="Hapus BAST?"
        message={<>BAST “{bast.title}” (belum terbit) akan dihapus.</>}
        confirmLabel="Hapus"
        danger
        onConfirm={async () => {
          try {
            await api.delete(`/bast/${id}`);
            void queryClient.invalidateQueries({ queryKey: ["bast"] });
            void queryClient.invalidateQueries({ queryKey: ["spk", "progress", bast.spk.id] });
            router.replace(`/spk-bast/spk/${bast.spk.id}`);
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

// --------------------------------------------------------------------------- form

const lineSchema = z.object({
  rab_item_id: z.string(),
  description: z.string().trim().min(1, "Uraian wajib diisi.").max(500),
  quantity: decimalString({ integerDigits: 14, fractionDigits: 4, positive: true, label: "Volume" }).refine((v) => v !== "", "Wajib."),
  unit: z.string().trim().min(1, "Wajib.").max(32),
  condition: optionalText(500),
});

export const bastFormSchema = z
  .object({
    title: z.string().trim().min(1, "Judul wajib diisi.").max(300),
    handover_date: z.string(),
    location: optionalText(300),
    delivered_by_name: optionalText(200),
    delivered_by_title: optionalText(200),
    received_by_name: optionalText(200),
    received_by_title: optionalText(200),
    terms: optionalText(10_000),
    notes: optionalText(10_000),
    items: z.array(lineSchema).max(500),
  })
  .refine(
    (v) => {
      const linked = v.items.map((i) => i.rab_item_id).filter(Boolean);
      return new Set(linked).size === linked.length;
    },
    { path: ["items"], message: "Satu item kontrak hanya boleh muncul sekali." },
  );
export type BastFormValues = z.infer<typeof bastFormSchema>;
const HEADER_FIELDS = [
  "title",
  "handover_date",
  "location",
  "delivered_by_name",
  "delivered_by_title",
  "received_by_name",
  "received_by_title",
  "terms",
  "notes",
] as const;

function trimZeros(value: string): string {
  return value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
}

export function bastPayload(bast: Pick<Bast, "version">, values: BastFormValues) {
  const { items, ...header } = values;
  return {
    ...blankToNull(header),
    version: bast.version,
    items: items.map((i) => ({
      rab_item_id: i.rab_item_id || null,
      description: i.description.trim(),
      quantity: i.quantity.trim(),
      unit: i.unit.trim(),
      condition: i.condition.trim() || null,
    })),
  };
}

/** Puts the server's per-line errors (loc ["body", "items", n, field]) on the matching inputs. */
export function applyLineErrors(error: unknown, setError: UseFormSetError<BastFormValues>): boolean {
  if (!(error instanceof ApiError) || error.status !== 422 || !Array.isArray(error.details)) return false;
  let applied = false;
  for (const item of error.details as { loc?: unknown[]; msg?: string }[]) {
    const loc = item.loc ?? [];
    if (loc[0] === "body" && loc[1] === "items" && typeof loc[2] === "number" && typeof loc[3] === "string") {
      setError(`items.${loc[2]}.${loc[3]}` as FieldPath<BastFormValues>, { type: "server", message: item.msg });
      applied = true;
    }
  }
  return applied;
}

function BastForm({
  bast,
  contract,
  onSaved,
}: {
  bast: Bast;
  contract: ContractItemProgress[];
  onSaved: (b: Bast) => void;
}) {
  const [formError, setFormError] = useState<string | null>(null);
  const byId = new Map(contract.map((c) => [c.rab_item_id, c]));
  const {
    register,
    control,
    handleSubmit,
    setError,
    setValue,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<BastFormValues>({
    resolver: zodResolver(bastFormSchema),
    values: {
      title: bast.title,
      handover_date: bast.handover_date ?? "",
      location: bast.location ?? "",
      delivered_by_name: bast.delivered_by_name ?? "",
      delivered_by_title: bast.delivered_by_title ?? "",
      received_by_name: bast.received_by_name ?? "",
      received_by_title: bast.received_by_title ?? "",
      terms: bast.terms ?? "",
      notes: bast.notes ?? "",
      items: bast.items.map((i) => ({
        rab_item_id: i.rab_item_id ?? "",
        description: i.description,
        quantity: trimZeros(i.quantity),
        unit: i.unit,
        condition: i.condition ?? "",
      })),
    },
  });
  const lines = useFieldArray({ control, name: "items" });
  const items = useWatch({ control, name: "items" });

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      onSaved(await api.patch<Bast>(`/bast/${bast.id}`, bastPayload(bast, values)));
      toast.success("BAST disimpan.");
    } catch (error) {
      const lineErrors = applyLineErrors(error, setError);
      const message = applyServerErrors(error, setError, HEADER_FIELDS);
      setFormError(lineErrors ? errorMessage(error) : message);
    }
  });

  const pickContractItem = (index: number, itemId: string) => {
    setValue(`items.${index}.rab_item_id`, itemId, { shouldDirty: true });
    const item = byId.get(itemId);
    if (item) {
      setValue(`items.${index}.description`, item.name, { shouldDirty: true });
      setValue(`items.${index}.unit`, item.unit, { shouldDirty: true });
    }
  };

  return (
    <Card title="Isi BAST">
      <form onSubmit={submit} noValidate className="space-y-4">
        <FormError message={formError} />
        <p className="text-xs text-muted">
          Catat hanya pekerjaan/barang yang benar-benar diserahkan. Untuk diajukan: tanggal serah terima, nama kedua pihak,
          dan minimal satu baris.
        </p>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Judul" error={errors.title?.message} required className="sm:col-span-2">
            {(a) => <Input {...a} {...register("title")} />}
          </Field>
          <Field label="Tanggal serah terima" error={errors.handover_date?.message}>
            {(a) => <Input type="date" {...a} {...register("handover_date")} />}
          </Field>
        </div>
        <Field label="Lokasi" error={errors.location?.message}>
          {(a) => <Input {...a} {...register("location")} />}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Yang menyerahkan" error={errors.delivered_by_name?.message}>
            {(a) => <Input {...a} {...register("delivered_by_name")} />}
          </Field>
          <Field label="Jabatan yang menyerahkan" error={errors.delivered_by_title?.message}>
            {(a) => <Input {...a} {...register("delivered_by_title")} />}
          </Field>
          <Field label="Yang menerima" error={errors.received_by_name?.message}>
            {(a) => <Input {...a} {...register("received_by_name")} />}
          </Field>
          <Field label="Jabatan yang menerima" error={errors.received_by_title?.message}>
            {(a) => <Input {...a} {...register("received_by_title")} />}
          </Field>
        </div>

        <div className="space-y-2">
          <p className="text-sm font-medium">Pekerjaan / barang yang diserahkan</p>
          {errors.items?.root?.message || errors.items?.message ? (
            <p className="text-xs text-danger">{errors.items?.root?.message ?? errors.items?.message}</p>
          ) : null}
          {lines.fields.map((field, index) => {
            const linked = byId.get(items[index]?.rab_item_id ?? "");
            const lineErrors = errors.items?.[index];
            return (
              <fieldset key={field.id} className="space-y-2 rounded-md border border-border p-2" aria-label={`Baris ${index + 1}`}>
                <div className="grid gap-2 sm:grid-cols-12">
                  <Select
                    aria-label={`Item kontrak baris ${index + 1}`}
                    className="sm:col-span-12"
                    value={items[index]?.rab_item_id ?? ""}
                    onChange={(e) => pickContractItem(index, e.target.value)}
                  >
                    <option value="">Di luar rincian kontrak</option>
                    {contract.map((c) => (
                      <option key={c.rab_item_id} value={c.rab_item_id}>
                        {c.no}. {c.name} (sisa {formatQuantity(c.remaining_quantity)} {c.unit})
                      </option>
                    ))}
                  </Select>
                  <Input aria-label={`Uraian baris ${index + 1}`} className="sm:col-span-6" {...register(`items.${index}.description`)} />
                  <Input
                    aria-label={`Volume baris ${index + 1}`}
                    className="tabular sm:col-span-2"
                    inputMode="decimal"
                    {...register(`items.${index}.quantity`)}
                  />
                  <Input
                    aria-label={`Satuan baris ${index + 1}`}
                    className="sm:col-span-2"
                    readOnly={Boolean(linked)}
                    title={linked ? "Satuan mengikuti kontrak" : undefined}
                    {...register(`items.${index}.unit`)}
                  />
                  <Button variant="ghost" size="sm" aria-label={`Hapus baris ${index + 1}`} className="sm:col-span-2" onClick={() => lines.remove(index)}>
                    <Trash2 className="size-4" />
                  </Button>
                  <Input
                    aria-label={`Kondisi baris ${index + 1}`}
                    placeholder="Kondisi / catatan (opsional, sesuai pemeriksaan)"
                    className="sm:col-span-12"
                    {...register(`items.${index}.condition`)}
                  />
                </div>
                {linked && (
                  <p className="text-xs text-muted">
                    Kontrak {formatQuantity(linked.contract_quantity)} {linked.unit} · sudah diserahkan{" "}
                    {formatQuantity(linked.delivered_quantity)} · sisa {formatQuantity(linked.remaining_quantity)}
                  </p>
                )}
                {lineErrors && (
                  <p className="text-xs text-danger">
                    {Object.values(lineErrors)
                      .map((e) => (e as { message?: string }).message)
                      .filter(Boolean)
                      .join(" ")}
                  </p>
                )}
              </fieldset>
            );
          })}
          <Button
            size="sm"
            variant="secondary"
            onClick={() => lines.append({ rab_item_id: "", description: "", quantity: "", unit: "", condition: "" })}
          >
            <Plus aria-hidden className="size-4" />
            Tambah baris
          </Button>
        </div>

        <Field label="Ketentuan" error={errors.terms?.message} hint="Diisi dari template BAST. Aplikasi tidak menambahkan kondisi serah terima.">
          {(a) => <Textarea rows={2} {...a} {...register("terms")} />}
        </Field>
        <Field label="Catatan" error={errors.notes?.message}>
          {(a) => <Textarea rows={2} {...a} {...register("notes")} />}
        </Field>
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-muted">Volume diperiksa server terhadap sisa kontrak saat disimpan, diajukan, dan diterbitkan.</p>
          <Button type="submit" size="sm" loading={isSubmitting} disabled={!isDirty}>
            Simpan
          </Button>
        </div>
      </form>
    </Card>
  );
}

function BastText({ bast, contract }: { bast: Bast; contract: ContractItemProgress[] }) {
  const byId = new Map(contract.map((c) => [c.rab_item_id, c]));
  return (
    <Card title="Isi BAST">
      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-muted">Tanggal serah terima</dt>
          <dd>{bast.handover_date ? formatTanggal(bast.handover_date) : "-"}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Lokasi</dt>
          <dd>{bast.location ?? "-"}</dd>
        </div>
      </dl>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] text-sm" aria-label="Baris BAST">
          <thead className="text-left text-xs text-muted">
            <tr>
              <th className="py-1 pr-2">Uraian</th>
              <th className="py-1 pr-2 text-right">Volume</th>
              <th className="py-1">Kondisi / catatan</th>
            </tr>
          </thead>
          <tbody>
            {bast.items.map((i) => {
              const linked = i.rab_item_id ? byId.get(i.rab_item_id) : undefined;
              return (
                <tr key={i.id} className="border-t border-border align-top">
                  <td className="py-1.5 pr-2">
                    {i.description}
                    <div className="text-xs text-muted">{linked ? `Item kontrak no. ${linked.no}` : i.rab_item_id ? "Item kontrak" : "Di luar rincian kontrak"}</div>
                  </td>
                  <td className="py-1.5 pr-2 text-right tabular whitespace-nowrap">
                    {formatQuantity(i.quantity)} {i.unit}
                  </td>
                  <td className="py-1.5 text-xs">{i.condition ?? "-"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {[
        ["Ketentuan", bast.terms],
        ["Catatan", bast.notes],
      ].map(
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

function Party({ role, name, title }: { role: string; name: string | null; title: string | null }) {
  return (
    <div>
      <p className="text-xs text-muted">{role}</p>
      <p>
        {name ?? <span className="text-muted">Belum diisi</span>}
        {title && <span className="text-muted">, {title}</span>}
      </p>
    </div>
  );
}

function BackLink() {
  return (
    <Link href="/spk-bast?tab=bast" className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground">
      <ArrowLeft aria-hidden className="size-4" />
      Kembali ke daftar BAST
    </Link>
  );
}
