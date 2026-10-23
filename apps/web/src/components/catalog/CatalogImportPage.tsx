"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, FileUp } from "lucide-react";
import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { FormError } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { Pagination } from "@/components/ui/Pagination";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Table, TableMessage, Td, Th } from "@/components/ui/Table";
import { API_BASE, apiFetch, api, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { formatTanggal, formatUnitPrice } from "@/lib/format";
import type { ImportJob, ImportRow } from "@/lib/types";

const MAX_BYTES = 5 * 1024 * 1024;
const ROWS_PER_PAGE = 50;
const COLUMNS = 7;

export function CatalogImportPage() {
  const canWrite = useCan("pricing.write");
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<ImportJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"upload" | "commit" | "discard" | null>(null);
  const [confirming, setConfirming] = useState(false);

  const upload = async () => {
    if (!file) {
      setError("Pilih file .xlsx atau .csv terlebih dahulu.");
      return;
    }
    if (file.size > MAX_BYTES) {
      setError("Ukuran file melebihi 5 MB.");
      return;
    }
    setBusy("upload");
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      setJob(await apiFetch<ImportJob>("/price-catalog/imports", { method: "POST", body }));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
    }
  };

  const finish = async (action: "commit" | "discard") => {
    if (!job) return;
    setBusy(action);
    setError(null);
    try {
      const updated = await api.post<ImportJob>(`/price-catalog/imports/${job.id}/${action}`);
      setJob(updated);
      if (action === "commit") {
        void queryClient.invalidateQueries({ queryKey: ["price-catalog"] });
        void queryClient.invalidateQueries({ queryKey: ["suppliers"] });
        toast.success("Impor selesai.");
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
      setConfirming(false);
    }
  };

  const restart = () => {
    setJob(null);
    setFile(null);
    setError(null);
    if (fileInput.current) fileInput.current.value = "";
  };

  if (!canWrite) {
    return (
      <div className="space-y-4">
        <BackLink />
        <PageHeader
          title="Impor katalog harga"
          description="Peran Anda tidak memiliki izin menambah data katalog."
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <BackLink />
      <PageHeader
        title="Impor katalog harga"
        description="Tambahkan banyak item dan harga sekaligus dari spreadsheet. Data diperiksa dulu sebelum disimpan."
      />
      <FormError message={error} />

      {!job && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card title="1. Siapkan file">
            <div className="flex flex-wrap gap-2">
              <TemplateLink format="xlsx" label="Template Excel (.xlsx)" />
              <TemplateLink format="csv" label="Template CSV" />
            </div>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
              <li>
                Kolom wajib: <strong>nama</strong>, <strong>satuan</strong>, <strong>harga</strong>,{" "}
                <strong>tanggal_harga</strong>.
              </li>
              <li>
                Harga ditulis tanpa pemisah ribuan (<code>4500</code> atau <code>4500,75</code>); nilai
                ambigu seperti <code>4.500</code> ditolak.
              </li>
              <li>Sel berisi rumus ditolak. Isi nilai akhirnya saja.</li>
              <li>Maksimal 5 MB dan 5.000 baris.</li>
              <li>Semua harga hasil impor berstatus belum terverifikasi.</li>
            </ul>
          </Card>
          <Card title="2. Unggah & periksa">
            <input
              ref={fileInput}
              type="file"
              aria-label="File spreadsheet"
              accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setError(null);
              }}
              className="block w-full text-sm file:mr-3 file:rounded-md file:border file:border-border file:bg-surface file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-surface-muted"
            />
            <Button onClick={() => void upload()} loading={busy === "upload"} disabled={!file}>
              <FileUp aria-hidden className="size-4" />
              Periksa file
            </Button>
          </Card>
        </div>
      )}

      {job && (
        <ImportPreview
          job={job}
          busy={busy}
          onCommit={() => setConfirming(true)}
          onDiscard={() => void finish("discard")}
          onRestart={restart}
        />
      )}

      <ConfirmDialog
        open={confirming}
        title="Simpan hasil impor?"
        message={
          <>
            {job?.valid_count ?? 0} baris valid akan disimpan sebagai harga <strong>belum terverifikasi</strong>.
            {job && job.error_count > 0 && ` ${job.error_count} baris bermasalah dilewati.`}
          </>
        }
        confirmLabel="Simpan"
        loading={busy === "commit"}
        onConfirm={() => void finish("commit")}
        onClose={() => setConfirming(false)}
      />
    </div>
  );
}

export function ImportPreview({
  job,
  busy,
  onCommit,
  onDiscard,
  onRestart,
}: {
  job: ImportJob;
  busy: "upload" | "commit" | "discard" | null;
  onCommit: () => void;
  onDiscard: () => void;
  onRestart: () => void;
}) {
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [page, setPage] = useState(1);
  const rows = useMemo(() => (onlyErrors ? job.rows.filter((r) => !r.valid) : job.rows), [job.rows, onlyErrors]);
  const visible = rows.slice((page - 1) * ROWS_PER_PAGE, page * ROWS_PER_PAGE);
  const previewing = job.status === "previewed";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3 text-sm">
        <span className="font-medium break-all">{job.filename}</span>
        <span className="text-muted">{job.row_count} baris</span>
        <StatusBadge tone="success">{`${job.valid_count} valid`}</StatusBadge>
        {job.error_count > 0 && <StatusBadge tone="danger">{`${job.error_count} bermasalah`}</StatusBadge>}
        {job.status === "committed" && <StatusBadge tone="success">Tersimpan</StatusBadge>}
        {job.status === "discarded" && <StatusBadge tone="neutral">Dibatalkan</StatusBadge>}
        <div className="ml-auto flex flex-wrap gap-2">
          {previewing ? (
            <>
              <Button variant="secondary" onClick={onDiscard} loading={busy === "discard"} disabled={busy !== null}>
                Batalkan
              </Button>
              <Button onClick={onCommit} disabled={job.valid_count === 0 || busy !== null}>
                Simpan {job.valid_count} baris valid
              </Button>
            </>
          ) : (
            <Button variant="secondary" onClick={onRestart}>
              Impor file lain
            </Button>
          )}
        </div>
      </div>

      {job.result && (
        <div role="status" className="rounded-md border border-success/30 bg-success-soft px-3 py-2 text-sm text-success">
          {job.result.items_created ?? 0} item baru, {job.result.prices_created ?? 0} harga, dan{" "}
          {job.result.suppliers_created ?? 0} supplier baru disimpan.{" "}
          <Link href="/katalog-harga" className="font-medium underline">
            Lihat katalog
          </Link>
        </div>
      )}

      {job.warnings.length > 0 && (
        <ul className="space-y-1 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm text-warning">
          {job.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      {job.error_count > 0 && (
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4 accent-primary"
            checked={onlyErrors}
            onChange={(e) => {
              setOnlyErrors(e.target.checked);
              setPage(1);
            }}
          />
          Tampilkan hanya baris bermasalah
        </label>
      )}

      <Table label="Pratinjau impor">
        <thead>
          <tr>
            <Th>Baris</Th>
            <Th>Hasil</Th>
            <Th>Item</Th>
            <Th className="text-right">Harga</Th>
            <Th>Tanggal</Th>
            <Th>Sumber</Th>
            <Th>Kesalahan</Th>
          </tr>
        </thead>
        <tbody>
          {visible.length === 0 && <TableMessage columns={COLUMNS}>Tidak ada baris.</TableMessage>}
          {visible.map((row) => (
            <PreviewRow key={row.row} row={row} />
          ))}
        </tbody>
      </Table>
      {rows.length > ROWS_PER_PAGE && (
        <Pagination page={page} pageSize={ROWS_PER_PAGE} total={rows.length} onPageChange={setPage} />
      )}
    </div>
  );
}

function PreviewRow({ row }: { row: ImportRow }) {
  const d = row.data;
  return (
    <tr className={`align-top ${row.valid ? "" : "bg-danger-soft/40"}`}>
      <Td className="tabular text-muted">{row.row}</Td>
      <Td>
        {row.valid ? (
          <StatusBadge tone={row.action === "create_item" ? "success" : "neutral"}>
            {row.action === "create_item" ? "Item baru" : "Tambah harga"}
          </StatusBadge>
        ) : (
          <StatusBadge tone="danger">Dilewati</StatusBadge>
        )}
      </Td>
      <Td>
        <div className="font-medium">{d.name ?? "—"}</div>
        <div className="text-xs text-muted">
          {[d.code, d.brand, d.unit && `per ${d.unit}`].filter(Boolean).join(" · ")}
        </div>
      </Td>
      <Td className="text-right tabular whitespace-nowrap">
        {d.price ? formatUnitPrice(d.price, d.currency ?? "IDR") : "—"}
      </Td>
      <Td className="whitespace-nowrap">{d.observed_at ? formatTanggal(d.observed_at) : "—"}</Td>
      <Td className="max-w-48 text-xs break-words text-muted">
        {[d.supplier, d.source_reference].filter(Boolean).join(" · ") || "—"}
      </Td>
      <Td className="max-w-64 text-xs text-danger">
        {row.errors.length > 0 && (
          <ul className="space-y-0.5">
            {row.errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        )}
      </Td>
    </tr>
  );
}

function TemplateLink({ format, label }: { format: "xlsx" | "csv"; label: string }) {
  return (
    <a
      href={`${API_BASE}/price-catalog/imports/template?format=${format}`}
      download
      className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-surface px-3.5 text-sm font-medium hover:bg-surface-muted"
    >
      <Download aria-hidden className="size-4" />
      {label}
    </a>
  );
}

function BackLink() {
  return (
    <Link href="/katalog-harga" className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground">
      <ArrowLeft aria-hidden className="size-4" />
      Kembali ke katalog harga
    </Link>
  );
}
