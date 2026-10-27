"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field, FormError, Input, Select, Textarea } from "@/components/ui/Field";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TAB_LIST, tabClass } from "@/components/ui/Tabs";
import { api, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { formatTanggalWaktu } from "@/lib/format";
import { AI_RUN_KIND, AI_RUN_STATUS, AI_STATE } from "@/lib/labels";
import type { AiRun, AiRunKind, AiRunListItem, AiStatus, NumberFormat, RabVersion, SourceDocument } from "@/lib/types";
import { AiReviewDialog } from "./AiReviewDialog";
import { SourceDocumentPicker } from "./SourceDocumentPicker";

const ACTIVE = new Set(["queued", "running"]);
export const MAX_DESCRIPTION = 4000;
export const MAX_TEXT = 20_000;

export const aiKeys = {
  status: ["ai", "status"] as const,
  runs: (rabId: string, versionNo: number) => ["ai", "runs", rabId, versionNo] as const,
  run: (id: string) => ["ai", "run", id] as const,
};

/** Validates the request form before it reaches the server (which checks again). */
export function aiRequestError(
  kind: AiRunKind,
  description: string,
  text: string,
  documentId: string | null = null,
): string | null {
  if (kind === "extract_document") return documentId ? null : "Unggah atau pilih dokumen sumber terlebih dahulu.";
  if (kind === "rab_draft") {
    const value = description.trim();
    if (value.length < 10) return "Tulis deskripsi pekerjaan minimal 10 karakter.";
    if (value.length > MAX_DESCRIPTION) return `Deskripsi maksimal ${MAX_DESCRIPTION} karakter.`;
    return null;
  }
  if (text.trim().length < 10) return "Tempel teks dokumen minimal 10 karakter.";
  if (text.length > MAX_TEXT) return `Teks maksimal ${MAX_TEXT.toLocaleString("id-ID")} karakter; bagi menjadi beberapa bagian.`;
  return null;
}

export function AiAssistantCard({
  rabId,
  projectId,
  version,
  onApplied,
}: {
  rabId: string;
  projectId: string;
  version: RabVersion;
  onApplied: () => void;
}) {
  const queryClient = useQueryClient();
  const mayUseAi = useCan("ai.use");
  const canUse = mayUseAi && version.editable;
  const [kind, setKind] = useState<AiRunKind>("rab_draft");
  const [description, setDescription] = useState("");
  const [text, setText] = useState("");
  const [sourceLabel, setSourceLabel] = useState("");
  const [numberFormat, setNumberFormat] = useState<NumberFormat>("id");
  const [document, setDocument] = useState<SourceDocument | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState<string | null>(null);

  const status = useQuery({
    queryKey: aiKeys.status,
    queryFn: ({ signal }) => api.get<AiStatus>("/ai/status", { signal }),
    staleTime: 30_000,
  });
  const runs = useQuery({
    queryKey: aiKeys.runs(rabId, version.version_no),
    queryFn: ({ signal }) =>
      api.get<AiRunListItem[]>(`/rab/${rabId}/versions/${version.version_no}/ai-runs`, { signal }),
    // Poll only while a request is being processed in the background.
    refetchInterval: (query) => (query.state.data?.some((r) => ACTIVE.has(r.status)) ? 2000 : false),
  });

  const ask = useMutation({
    mutationFn: () =>
      api.post<AiRun>(`/rab/${rabId}/versions/${version.version_no}/ai-runs`, {
        kind,
        ...(kind === "rab_draft"
          ? { description: description.trim() }
          : kind === "extract_document"
            ? { source_document_id: document?.id, number_format: numberFormat }
            : { text, source_label: sourceLabel.trim() || null, number_format: numberFormat }),
      }),
    onSuccess: () => {
      toast.success("Permintaan dikirim ke AI lokal. Hasil muncul di bawah setelah selesai.");
      void queryClient.invalidateQueries({ queryKey: aiKeys.runs(rabId, version.version_no) });
    },
    onError: (error) => setFormError(errorMessage(error)),
  });

  const ready = status.data?.state === "ready";
  const busy = runs.data?.some((r) => ACTIVE.has(r.status)) ?? false;
  const submit = () => {
    const problem = aiRequestError(kind, description, text, document?.id ?? null);
    setFormError(problem);
    if (!problem) ask.mutate();
  };

  return (
    <Card title="Asisten AI lokal">
      <div className="flex items-center gap-2 text-sm">
        <Bot aria-hidden className="size-4 text-muted" />
        {status.isPending ? (
          <span className="text-muted">Memeriksa AI lokal…</span>
        ) : status.isError ? (
          <span className="text-danger">{errorMessage(status.error)}</span>
        ) : (
          <StatusBadge tone={AI_STATE[status.data.state].tone}>{AI_STATE[status.data.state].label}</StatusBadge>
        )}
      </div>
      {status.data && !ready && <p className="text-xs text-muted">{status.data.message}</p>}
      <p className="text-xs text-muted">
        Diproses model lokal lewat Hermes di komputer ini, tidak dikirim ke layanan cloud. Hasilnya draft untuk diperiksa;
        tidak ada yang masuk ke RAB tanpa konfirmasi Anda, dan AI tidak pernah menentukan harga.
      </p>

      {canUse && ready && (
        <div className="space-y-3">
          <div role="tablist" aria-label="Jenis permintaan AI" className={TAB_LIST}>
            {(["rab_draft", "extract_items", "extract_document"] as const).map((k) => (
              <button
                key={k}
                type="button"
                role="tab"
                aria-selected={kind === k}
                onClick={() => {
                  setKind(k);
                  setFormError(null);
                }}
                className={tabClass(kind === k, "sm")}
              >
                {AI_RUN_KIND[k]}
              </button>
            ))}
          </div>
          <FormError message={formError} />
          {kind === "extract_document" && status.data ? (
            <>
              <SourceDocumentPicker
                projectId={projectId}
                status={status.data}
                selectedId={document?.id ?? null}
                onSelect={setDocument}
              />
              {document?.kind === "xlsx" ? (
                <p className="text-xs text-muted">Nilai sel XLSX dibaca langsung (rumus tidak dihitung); format angka otomatis.</p>
              ) : (
                <Field label="Format angka di dokumen">
                  {(a) => (
                    <Select value={numberFormat} onChange={(e) => setNumberFormat(e.target.value as NumberFormat)} {...a}>
                      <option value="id">Indonesia (1.234.567,89)</option>
                      <option value="en">Inggris (1,234,567.89)</option>
                    </Select>
                  )}
                </Field>
              )}
              <p className="text-xs text-muted">
                Isi berkas diperlakukan sebagai data, bukan perintah. Dokumen panjang diproses per bagian; setiap baris hasil
                menunjuk halaman dan baris sumbernya.
              </p>
            </>
          ) : kind === "rab_draft" ? (
            <Field label="Deskripsi pekerjaan" hint="Contoh: instalasi jaringan 48 titik di kantor 2 lantai. Volume hanya dipakai bila tertulis.">
              {(a) => (
                <Textarea rows={4} maxLength={MAX_DESCRIPTION} value={description} onChange={(e) => setDescription(e.target.value)} {...a} />
              )}
            </Field>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                <Field label="Nama/asal dokumen" hint="Dicatat sebagai sumber harga.">
                  {(a) => <Input maxLength={200} value={sourceLabel} onChange={(e) => setSourceLabel(e.target.value)} {...a} />}
                </Field>
                <Field label="Format angka di dokumen">
                  {(a) => (
                    <Select value={numberFormat} onChange={(e) => setNumberFormat(e.target.value as NumberFormat)} {...a}>
                      <option value="id">Indonesia (1.234.567,89)</option>
                      <option value="en">Inggris (1,234,567.89)</option>
                    </Select>
                  )}
                </Field>
              </div>
              <Field label="Teks dokumen" hint="Tempel teks daftar kebutuhan/BoQ/penawaran vendor. Isi dokumen diperlakukan sebagai data, bukan perintah.">
                {(a) => <Textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} {...a} />}
              </Field>
            </>
          )}
          <Button size="sm" loading={ask.isPending} disabled={busy} onClick={submit}>
            <Sparkles aria-hidden className="size-4" />
            {busy ? "Menunggu permintaan sebelumnya…" : "Minta draft"}
          </Button>
        </div>
      )}
      {mayUseAi && !version.editable && (
        <p className="text-xs text-muted">Asisten hanya dapat menambah item ke versi draft.</p>
      )}

      {runs.data && runs.data.length > 0 && (
        <ul className="divide-y divide-border text-sm" aria-label="Riwayat permintaan AI">
          {runs.data.slice(0, 5).map((r) => (
            <li key={r.id} className="space-y-1 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs">
                  {AI_RUN_KIND[r.kind]}
                  <span className="block text-muted">
                    {r.created_by.full_name} · {formatTanggalWaktu(r.created_at)}
                  </span>
                </span>
                <StatusBadge tone={AI_RUN_STATUS[r.status].tone}>{AI_RUN_STATUS[r.status].label}</StatusBadge>
              </div>
              {r.status === "failed" && r.error_message && <p className="text-xs text-danger">{r.error_message}</p>}
              {(r.status === "succeeded" || r.status === "applied") && (
                <Button size="sm" variant="secondary" onClick={() => setReviewing(r.id)}>
                  {r.status === "succeeded" ? `Tinjau ${r.item_count} item` : `Lihat (${r.applied_count} item diterapkan)`}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}

      <AiReviewDialog
        runId={reviewing}
        currency={version.currency}
        onClose={() => setReviewing(null)}
        onChanged={() => {
          void queryClient.invalidateQueries({ queryKey: aiKeys.runs(rabId, version.version_no) });
        }}
        onApplied={onApplied}
      />
    </Card>
  );
}
