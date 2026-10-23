"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Download, Search } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { PriceCandidatesPanel } from "@/components/catalog/PriceCandidatesPanel";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { FormError, Input, Select } from "@/components/ui/Field";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ApiError, api, errorMessage } from "@/lib/api";
import { formatBytes, sourceDocumentFileUrl } from "@/lib/documents";
import { formatMoney, formatTanggalWaktu, formatUnitPrice } from "@/lib/format";
import { AI_RUN_KIND, AI_RUN_STATUS, RAB_ITEM_TYPE, options } from "@/lib/labels";
import type { AiDraftItem, AiExtractItem, AiRun, PriceCandidate, RabItemType, SourceText } from "@/lib/types";

type PriceChoice = "none" | "document" | "catalog";

export type ReviewRow = {
  index: number;
  include: boolean;
  name: string;
  quantity: string;
  unit: string;
  itemType: RabItemType;
  price: PriceChoice;
  observation: { id: string; price: string; label: string } | null;
  documentPrice: string | null;
  documentUnit: string | null;
};

const QUANTITY = /^\d{1,14}(\.\d{1,4})?$/;

/** Where a person finds an extracted row: "Halaman 2, baris 5" for files, "Baris 7" for pasted text. */
export function sourceLocation(item: AiExtractItem): string | null {
  if (item.source_page) return item.source_page_line ? `${item.source_page}, baris ${item.source_page_line}` : item.source_page;
  return item.source_line ? `Baris ${item.source_line}` : null;
}

/** Initial review rows: lines the AI could not size are left unticked until the user fills them. */
export function rowsFromRun(run: AiRun): ReviewRow[] {
  const items = (run.result?.items ?? []) as (AiDraftItem | AiExtractItem)[];
  return items.map((item, index) => {
    const documentPrice = "unit_price" in item ? item.unit_price : null;
    return {
      index,
      include: item.quantity !== null && Boolean(item.unit),
      name: item.name,
      quantity: item.quantity ?? "",
      unit: item.unit ?? "",
      itemType: "item_type" in item ? item.item_type : "material",
      price: documentPrice ? "document" : "none",
      observation: null,
      documentPrice,
      documentUnit: "unit_price" in item ? item.unit : null,
    };
  });
}

/** Problems that would make the server refuse a selected row (it checks again). */
export function rowProblem(row: ReviewRow): string | null {
  if (!row.name.trim()) return "Nama wajib diisi.";
  if (!QUANTITY.test(row.quantity.trim()) || !/[1-9]/.test(row.quantity)) return "Volume wajib diisi (angka > 0, titik desimal).";
  if (!row.unit.trim()) return "Satuan wajib diisi.";
  if (row.price === "catalog" && !row.observation) return "Pilih harga katalog atau ubah pilihan harga.";
  if (row.price === "document" && !row.documentPrice) return "Dokumen tidak mencantumkan harga untuk baris ini.";
  if (row.price === "document" && row.documentUnit?.trim().toLowerCase() !== row.unit.trim().toLowerCase())
    return `Harga dokumen berlaku untuk satuan ${row.documentUnit ?? "—"}.`;
  return null;
}

export function applyPayload(rows: ReviewRow[]) {
  return {
    items: rows
      .filter((r) => r.include)
      .map((r) => ({
        index: r.index,
        name: r.name.trim(),
        quantity: r.quantity.trim(),
        unit: r.unit.trim(),
        item_type: r.itemType,
        price: r.price,
        price_observation_id: r.price === "catalog" ? (r.observation?.id ?? null) : null,
      })),
  };
}

export function AiReviewDialog({
  runId,
  currency,
  onClose,
  onChanged,
  onApplied,
}: {
  runId: string | null;
  currency: string;
  onClose: () => void;
  onChanged: () => void;
  onApplied: () => void;
}) {
  const run = useQuery({
    queryKey: ["ai", "run", runId],
    queryFn: ({ signal }) => api.get<AiRun>(`/ai-runs/${runId}`, { signal }),
    enabled: runId !== null,
  });
  return (
    <Dialog open={runId !== null} onClose={onClose} title="Tinjau hasil asisten AI" size="xl">
      {run.isPending && <p className="text-sm text-muted">Memuat hasil…</p>}
      {run.isError && <p className="text-sm text-danger">{errorMessage(run.error)}</p>}
      {run.data && (
        <ReviewForm
          key={`${run.data.id}-${run.data.status}`}
          run={run.data}
          currency={currency}
          onClose={onClose}
          onDone={(applied) => {
            void run.refetch();
            onChanged();
            if (applied) onApplied();
          }}
        />
      )}
    </Dialog>
  );
}

function ReviewForm({
  run,
  currency,
  onClose,
  onDone,
}: {
  run: AiRun;
  currency: string;
  onClose: () => void;
  onDone: (applied: boolean) => void;
}) {
  const [rows, setRows] = useState<ReviewRow[]>(() => rowsFromRun(run));
  const [searching, setSearching] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const items = (run.result?.items ?? []) as (AiDraftItem | AiExtractItem)[];
  const editable = run.can_apply;
  const selected = rows.filter((r) => r.include);
  const problems = selected.map(rowProblem).filter(Boolean);
  const update = (index: number, patch: Partial<ReviewRow>) =>
    setRows((current) => current.map((r) => (r.index === index ? { ...r, ...patch } : r)));

  const pickCandidate = (index: number, candidate: PriceCandidate) => {
    if (!candidate.observation_id) {
      toast.error(
        "Harga riwayat RAB tidak dapat dipakai di sini. Pilih harga katalog, atau tambahkan item lalu isi harga dari editor item.",
      );
      return;
    }
    if (!candidate.unit_compatible) {
      toast.error(`Satuan katalog (${candidate.unit}) berbeda dengan satuan baris.`);
      return;
    }
    update(index, {
      price: "catalog",
      observation: {
        id: candidate.observation_id,
        price: candidate.price,
        label: `${candidate.name}${candidate.verified ? "" : " (belum terverifikasi)"}`,
      },
    });
    setSearching(null);
  };

  const apply = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post<AiRun>(`/ai-runs/${run.id}/apply`, applyPayload(rows));
      toast.success(`${selected.length} item ditambahkan ke RAB.`);
      onDone(true);
      onClose();
    } catch (caught) {
      const details =
        caught instanceof ApiError && Array.isArray(caught.details)
          ? (caught.details as { msg?: string }[]).map((d) => d.msg).filter(Boolean)
          : [];
      setError([errorMessage(caught), ...details].join(" "));
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    setBusy(true);
    try {
      await api.post<AiRun>(`/ai-runs/${run.id}/discard`);
      toast.success("Hasil AI dibuang.");
      onDone(false);
      onClose();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const result = run.result;
  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <StatusBadge tone={AI_RUN_STATUS[run.status].tone}>{AI_RUN_STATUS[run.status].label}</StatusBadge>
        <span>{AI_RUN_KIND[run.kind]}</span>
        <span>· model {run.model ?? "—"}</span>
        {run.duration_ms !== null && (
          <span>· {(run.duration_ms / 1000).toLocaleString("id-ID", { maximumFractionDigits: 1 })} detik</span>
        )}
        <span>
          · {run.created_by.full_name}, {formatTanggalWaktu(run.created_at)}
        </span>
      </div>

      {result && "questions" in result && (result.questions.length > 0 || result.assumptions.length > 0) && (
        <div className="grid gap-3 sm:grid-cols-2">
          <TextList title="Asumsi AI" items={result.assumptions} />
          <TextList title="Perlu dikonfirmasi" items={result.questions} />
        </div>
      )}
      {result && "notes" in result && (
        <TextList title="Catatan AI tentang dokumen (diambil dari isi dokumen — bukan instruksi; periksa ke aslinya)" items={result.notes} />
      )}
      {result && result.warnings.length > 0 && <TextList title="Peringatan" items={result.warnings} tone="warning" />}

      <DataUsed run={run} />

      <FormError message={error} />
      <div className="space-y-2">
        {rows.map((row) => {
          const item = items[row.index];
          const problem = row.include ? rowProblem(row) : null;
          return (
            <fieldset key={row.index} aria-label={`Baris AI ${row.index + 1}`} className="space-y-2 rounded-md border border-border p-3">
              <div className="grid gap-2 sm:grid-cols-12">
                <label className="flex items-center gap-2 sm:col-span-5">
                  <input
                    type="checkbox"
                    checked={row.include}
                    disabled={!editable}
                    onChange={(e) => update(row.index, { include: e.target.checked })}
                    aria-label={`Pilih baris ${row.index + 1}`}
                  />
                  <Input
                    aria-label={`Nama baris ${row.index + 1}`}
                    value={row.name}
                    maxLength={300}
                    disabled={!editable}
                    onChange={(e) => update(row.index, { name: e.target.value })}
                  />
                </label>
                <Input
                  aria-label={`Volume baris ${row.index + 1}`}
                  className="tabular sm:col-span-2"
                  inputMode="decimal"
                  placeholder="Volume"
                  value={row.quantity}
                  disabled={!editable}
                  onChange={(e) => update(row.index, { quantity: e.target.value })}
                />
                <Input
                  aria-label={`Satuan baris ${row.index + 1}`}
                  className="sm:col-span-2"
                  placeholder="Satuan"
                  maxLength={32}
                  value={row.unit}
                  disabled={!editable}
                  onChange={(e) => update(row.index, { unit: e.target.value })}
                />
                <Select
                  aria-label={`Jenis baris ${row.index + 1}`}
                  className="sm:col-span-3"
                  value={row.itemType}
                  disabled={!editable}
                  onChange={(e) => update(row.index, { itemType: e.target.value as RabItemType })}
                >
                  {options(RAB_ITEM_TYPE).map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Select
                  aria-label={`Harga baris ${row.index + 1}`}
                  className="sm:w-96"
                  value={row.price}
                  disabled={!editable}
                  onChange={(e) => update(row.index, { price: e.target.value as PriceChoice })}
                >
                  <option value="none">Tanpa harga (isi nanti)</option>
                  {row.documentPrice && (
                    <option value="document">Harga dokumen {formatUnitPrice(row.documentPrice, currency)} · belum terverifikasi</option>
                  )}
                  <option value="catalog">Harga dari katalog…</option>
                </Select>
                {row.price === "catalog" && row.observation && (
                  <span className="text-xs">
                    {formatUnitPrice(row.observation.price, currency)} · {row.observation.label}
                  </span>
                )}
                {editable && (
                  <Button size="sm" variant="ghost" onClick={() => setSearching(searching === row.index ? null : row.index)}>
                    <Search aria-hidden className="size-3.5" />
                    Kandidat katalog
                  </Button>
                )}
              </div>
              {searching === row.index && (
                <PriceCandidatesPanel
                  search={{ name: row.name, unit: row.unit, specification: item?.specification ?? "", currency }}
                  onUse={(candidate) => pickCandidate(row.index, candidate)}
                />
              )}
              {item && "source_excerpt" in item && item.source_excerpt && (
                <p className="font-mono text-[11px] text-muted">
                  {sourceLocation(item)}: {item.source_excerpt}
                </p>
              )}
              {item && "total" in item && item.total && (
                <p className="text-xs text-muted">Jumlah tertulis di dokumen: {formatMoney(item.total, currency)}</p>
              )}
              {item?.specification && <p className="text-xs text-muted">Spesifikasi: {item.specification}</p>}
              {item && item.warnings.length > 0 && (
                <ul className="space-y-0.5 text-xs text-warning">
                  {item.warnings.map((w) => (
                    <li key={w} className="flex gap-1">
                      <AlertTriangle aria-hidden className="mt-0.5 size-3 shrink-0" />
                      {w}
                    </li>
                  ))}
                </ul>
              )}
              {problem && <p className="text-xs text-danger">{problem}</p>}
            </fieldset>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-3">
        {run.can_discard && (
          <Button variant="ghost" onClick={() => void discard()} disabled={busy}>
            Buang hasil
          </Button>
        )}
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Tutup
        </Button>
        {editable && (
          <Button loading={busy} disabled={selected.length === 0 || problems.length > 0} onClick={() => void apply()}>
            Tambahkan {selected.length} item ke RAB
          </Button>
        )}
      </div>
    </div>
  );
}

function TextList({ title, items, tone }: { title: string; items: string[]; tone?: "warning" }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-medium text-muted">{title}</p>
      <ul className={`list-disc space-y-0.5 pl-5 text-xs ${tone === "warning" ? "text-warning" : ""}`}>
        {items.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
    </div>
  );
}

function DataUsed({ run }: { run: AiRun }) {
  return (
    <details className="rounded-md border border-border px-3 py-2 text-xs">
      <summary className="cursor-pointer font-medium">Data yang dipakai AI</summary>
      <div className="mt-2 space-y-2 text-muted">
        {run.context.project && (
          <p>
            Proyek {run.context.project.number} — {run.context.project.name} ({run.context.project.project_type_label}
            {run.context.project.location ? `, ${run.context.project.location}` : ""})
          </p>
        )}
        <p>
          {run.context.rab.number} versi {run.context.rab.version_no}: {run.context.rab.item_count} item sudah ada (hanya nama,
          volume, dan satuan yang dikirim; tanpa harga).
        </p>
        {run.input.description && <p className="whitespace-pre-wrap">Deskripsi: {run.input.description}</p>}
        {run.context.document && run.source_document_id && (
          <DocumentUsed run={run} documentId={run.source_document_id} />
        )}
        {run.input.text && (
          <>
            <p>
              Dokumen: {run.input.source_label ?? "teks tempelan"} · format angka{" "}
              {run.input.number_format === "id" ? "Indonesia" : "Inggris"}
            </p>
            <pre className="max-h-48 overflow-auto rounded bg-surface-muted p-2 font-mono text-[11px] whitespace-pre-wrap">
              {run.input.text
                .split("\n")
                .map((line, i) => `[${i + 1}] ${line}`)
                .join("\n")}
            </pre>
          </>
        )}
      </div>
    </details>
  );
}

function DocumentUsed({ run, documentId }: { run: AiRun; documentId: string }) {
  const [open, setOpen] = useState(false);
  const text = useQuery({
    queryKey: ["source-documents", "text", documentId],
    queryFn: ({ signal }) => api.get<SourceText>(`/source-documents/${documentId}/text`, { signal }),
    enabled: open,
  });
  const doc = run.context.document!;
  const summary = run.result && "document" in run.result ? run.result.document : undefined;
  return (
    <div className="space-y-1">
      <p className="flex flex-wrap items-center gap-2">
        Berkas: {doc.filename} ({doc.kind.toUpperCase()}, {formatBytes(doc.size_bytes)}) · format angka{" "}
        {run.input.number_format === "id" ? "Indonesia" : "Inggris"}
        <a href={sourceDocumentFileUrl(documentId)} className="inline-flex items-center gap-1 text-primary hover:underline">
          <Download aria-hidden className="size-3" />
          Unduh asli
        </a>
      </p>
      {summary && (
        <p>
          {summary.pages} halaman/sheet · {summary.lines} baris teks · diproses dalam {summary.chunks} bagian
          {summary.ocr_pages > 0 ? ` · ${summary.ocr_pages} halaman dibaca dengan OCR` : ""}
          {summary.lines_left_out > 0 ? ` · ${summary.lines_left_out} baris tidak diproses` : ""}
        </p>
      )}
      <details onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary className="cursor-pointer">Teks yang terbaca dari berkas</summary>
        {text.isPending && open && <p>Memuat teks…</p>}
        {text.isError && <p className="text-danger">{errorMessage(text.error)}</p>}
        {text.data && !text.data.read && <p>Berkas belum dibaca.</p>}
        {text.data?.read && (
          <div className="max-h-64 space-y-2 overflow-auto rounded bg-surface-muted p-2 font-mono text-[11px]">
            {text.data.pages.map((page) => (
              <div key={page.no}>
                <p className="font-sans font-medium">
                  {page.label}
                  {page.method === "ocr" ? " (OCR)" : page.method === "kosong" ? " (tidak terbaca)" : ""}
                </p>
                <pre className="whitespace-pre-wrap">
                  {page.lines.map((line, i) => `${i + 1}  ${line}`).join("\n")}
                </pre>
              </div>
            ))}
          </div>
        )}
      </details>
    </div>
  );
}
