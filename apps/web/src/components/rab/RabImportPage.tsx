"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, FileUp } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Button, buttonClass } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { FormError } from "@/components/ui/Field";
import { FullPageMessage } from "@/components/ui/FullPageMessage";
import { PageHeader } from "@/components/ui/PageHeader";
import { Pagination } from "@/components/ui/Pagination";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Table, TableMessage, Td, Th } from "@/components/ui/Table";
import { API_BASE, apiFetch, api, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { formatMoney, formatQuantity, formatUnitPrice } from "@/lib/format";
import { RAB_ITEM_TYPE, RAB_STATUS } from "@/lib/labels";
import type { ImportJob, ImportRow, Rab, RabItemType, RabVersion } from "@/lib/types";

const MAX_BYTES = 5 * 1024 * 1024;
const ROWS_PER_PAGE = 50;
const COLUMNS = 7;

export function RabImportPage() {
  const { id } = useParams<{ id: string }>();
  const versionNo = Number(useSearchParams().get("versi"));
  const canWrite = useCan("rab.write");

  const rab = useQuery({
    queryKey: ["rab", id],
    queryFn: ({ signal }) => api.get<Rab>(`/rab/${id}`, { signal }),
    retry: false,
  });
  const version = useQuery({
    queryKey: ["rab", id, "version", versionNo],
    queryFn: ({ signal }) => api.get<RabVersion>(`/rab/${id}/versions/${versionNo}`, { signal }),
    enabled: Number.isInteger(versionNo) && versionNo > 0,
    retry: false,
  });

  if (!Number.isInteger(versionNo) || versionNo < 1) {
    return <Unavailable id={id} message="Versi RAB tidak valid." />;
  }
  if (rab.isPending || version.isPending) return <FullPageMessage loading title="Memuat RAB…" />;
  if (rab.isError) return <Unavailable id={id} message={errorMessage(rab.error)} />;
  if (version.isError) return <Unavailable id={id} message={errorMessage(version.error)} />;
  if (!canWrite) return <Unavailable id={id} message="Peran Anda tidak dapat mengubah RAB." />;

  const v = version.data;
  return (
    <div className="space-y-6">
      <BackLink id={id} versionNo={versionNo} />
      <PageHeader
        title="Impor item RAB"
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs">{rab.data.number}</span>
            <span>{rab.data.title}</span>
            <span>· versi {versionNo}</span>
            <StatusBadge tone={RAB_STATUS[v.status].tone}>{RAB_STATUS[v.status].label}</StatusBadge>
          </span>
        }
      />
      {v.status !== "draft" ? (
        <FormError message="Item hanya dapat diimpor ke versi berstatus draft. Buat versi baru terlebih dahulu." />
      ) : (
        <ImportFlow rabId={id} versionNo={versionNo} />
      )}
    </div>
  );
}

function ImportFlow({ rabId, versionNo }: { rabId: string; versionNo: number }) {
  const queryClient = useQueryClient();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<ImportJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"upload" | "commit" | "discard" | null>(null);
  const [confirming, setConfirming] = useState(false);
  const base = `/rab/${rabId}/versions/${versionNo}/imports`;

  const upload = async () => {
    if (!file) return;
    if (file.size > MAX_BYTES) {
      setError("Ukuran file melebihi 5 MB.");
      return;
    }
    setBusy("upload");
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      setJob(await apiFetch<ImportJob>(base, { method: "POST", body }));
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
      setJob(await api.post<ImportJob>(`${base}/${job.id}/${action}`));
      if (action === "commit") {
        void queryClient.invalidateQueries({ queryKey: ["rab"] });
        toast.success("Item ditambahkan ke RAB.");
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(null);
      setConfirming(false);
    }
  };

  return (
    <div className="space-y-5">
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
                Kolom wajib: <strong>nama</strong>, <strong>volume</strong>, <strong>satuan</strong>.
                Harga satuan boleh kosong.
              </li>
              <li>
                Angka tanpa pemisah ribuan (<code>4500</code> atau <code>4500,75</code>);{" "}
                <code>4.500</code> ditolak karena ambigu.
              </li>
              <li>Sel berisi rumus ditolak. Isi nilai akhirnya saja.</li>
              <li>Item ditambahkan di akhir daftar; item yang sudah ada tidak diubah.</li>
            </ul>
          </Card>
          <Card title="2. Unggah & periksa">
            <input
              ref={fileInput}
              type="file"
              aria-label="File spreadsheet"
              accept=".xlsx,.csv"
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
        <RabImportPreview
          job={job}
          busy={busy}
          backHref={`/rab/${rabId}?v=${versionNo}`}
          onCommit={() => setConfirming(true)}
          onDiscard={() => void finish("discard")}
          onRestart={() => {
            setJob(null);
            setFile(null);
            if (fileInput.current) fileInput.current.value = "";
          }}
        />
      )}

      <ConfirmDialog
        open={confirming}
        title="Tambahkan item?"
        message={
          <>
            {job?.valid_count ?? 0} item akan ditambahkan ke versi {versionNo}; total dihitung ulang
            oleh server.
            {job && job.error_count > 0 && ` ${job.error_count} baris bermasalah dilewati.`}
          </>
        }
        confirmLabel="Tambahkan"
        loading={busy === "commit"}
        onConfirm={() => void finish("commit")}
        onClose={() => setConfirming(false)}
      />
    </div>
  );
}

export function RabImportPreview({
  job,
  busy,
  backHref,
  onCommit,
  onDiscard,
  onRestart,
}: {
  job: ImportJob;
  busy: "upload" | "commit" | "discard" | null;
  backHref: string;
  onCommit: () => void;
  onDiscard: () => void;
  onRestart: () => void;
}) {
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [page, setPage] = useState(1);
  const rows = useMemo(() => (onlyErrors ? job.rows.filter((r) => !r.valid) : job.rows), [job.rows, onlyErrors]);
  const visible = rows.slice((page - 1) * ROWS_PER_PAGE, page * ROWS_PER_PAGE);

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
          {job.status === "previewed" ? (
            <>
              <Button variant="secondary" onClick={onDiscard} loading={busy === "discard"} disabled={busy !== null}>
                Batalkan
              </Button>
              <Button onClick={onCommit} disabled={job.valid_count === 0 || busy !== null}>
                Tambahkan {job.valid_count} item
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
          {job.result.items_created ?? 0} item ditambahkan.{" "}
          <Link href={backHref} className="font-medium underline">
            Kembali ke RAB
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

      <Table label="Pratinjau impor item">
        <thead>
          <tr>
            <Th>Baris</Th>
            <Th>Hasil</Th>
            <Th>Item</Th>
            <Th className="text-right">Volume</Th>
            <Th className="text-right">Harga satuan</Th>
            <Th className="text-right">Subtotal</Th>
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
  const type = d.item_type && d.item_type in RAB_ITEM_TYPE ? RAB_ITEM_TYPE[d.item_type as RabItemType] : null;
  return (
    <tr className={`align-top ${row.valid ? "" : "bg-danger-soft/40"}`}>
      <Td className="tabular text-muted">{row.row}</Td>
      <Td>
        {row.valid ? (
          <StatusBadge tone="success">Ditambahkan</StatusBadge>
        ) : (
          <StatusBadge tone="danger">Dilewati</StatusBadge>
        )}
      </Td>
      <Td>
        <div className="font-medium">{d.name ?? "-"}</div>
        <div className="text-xs text-muted">{[d.code, d.category, type].filter(Boolean).join(" · ")}</div>
      </Td>
      <Td className="text-right tabular whitespace-nowrap">
        {d.quantity ? `${formatQuantity(d.quantity)} ${d.unit ?? ""}` : "-"}
      </Td>
      <Td className="text-right tabular whitespace-nowrap">{d.unit_price ? formatUnitPrice(d.unit_price) : "-"}</Td>
      <Td className="text-right tabular whitespace-nowrap">{d.subtotal ? formatMoney(d.subtotal, "IDR") : "-"}</Td>
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
      href={`${API_BASE}/rab/item-imports/template?format=${format}`}
      download
      className={buttonClass({ variant: "secondary" })}
    >
      <Download aria-hidden className="size-4" />
      {label}
    </a>
  );
}

function BackLink({ id, versionNo }: { id: string; versionNo?: number }) {
  return (
    <Link
      href={versionNo ? `/rab/${id}?v=${versionNo}` : `/rab/${id}`}
      className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground"
    >
      <ArrowLeft aria-hidden className="size-4" />
      Kembali ke RAB
    </Link>
  );
}

function Unavailable({ id, message }: { id: string; message: string }) {
  return (
    <div className="space-y-4">
      <BackLink id={id} />
      <PageHeader title="Impor item RAB" description={message} />
    </div>
  );
}
