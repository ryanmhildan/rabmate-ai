"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileUp, ScanText } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Field, FormError, Select } from "@/components/ui/Field";
import { apiFetch, api, errorMessage } from "@/lib/api";
import { formatBytes, sourceDocumentFileUrl } from "@/lib/documents";
import { formatTanggalWaktu } from "@/lib/format";
import type { AiStatus, SourceDocument, SourceUpload } from "@/lib/types";

export const sourceKeys = {
  list: (projectId: string) => ["source-documents", projectId] as const,
  text: (documentId: string) => ["source-documents", "text", documentId] as const,
};

/** Client-side checks before an upload (the server sniffs the bytes and checks again). */
export function uploadProblem(file: File, status: Pick<AiStatus, "upload_max_mb" | "accepted_files">): string | null {
  if (file.size === 0) return "File kosong.";
  if (file.size > status.upload_max_mb * 1024 * 1024) return `Ukuran file melebihi ${status.upload_max_mb} MB.`;
  const name = file.name.toLowerCase();
  const accepted = status.accepted_files.split(",").map((ext) => ext.trim());
  if (!accepted.some((ext) => name.endsWith(ext))) return `Format tidak didukung. Unggah ${status.accepted_files}.`;
  return null;
}

export function SourceDocumentPicker({
  projectId,
  status,
  selectedId,
  onSelect,
}: {
  projectId: string;
  status: AiStatus;
  selectedId: string | null;
  onSelect: (document: SourceDocument | null) => void;
}) {
  const queryClient = useQueryClient();
  const inputId = useId();
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const documents = useQuery({
    queryKey: sourceKeys.list(projectId),
    queryFn: ({ signal }) => api.get<SourceDocument[]>(`/projects/${projectId}/source-documents`, { signal }),
  });
  const selected = documents.data?.find((d) => d.id === selectedId) ?? null;

  const upload = async (file: File | undefined) => {
    if (!file) return;
    const problem = uploadProblem(file, status);
    setError(problem);
    if (problem) return;
    setUploading(true);
    try {
      const body = new FormData();
      body.append("file", file);
      const saved = await apiFetch<SourceUpload>(`/projects/${projectId}/source-documents`, { method: "POST", body });
      toast.success(
        saved.duplicate
          ? `Berkas yang sama sudah pernah diunggah sebagai "${saved.filename}"; salinan itu dipakai.`
          : `"${saved.filename}" diunggah.`,
      );
      await queryClient.invalidateQueries({ queryKey: sourceKeys.list(projectId) });
      onSelect(saved);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-3">
      <FormError message={error} />
      <div className="flex flex-wrap items-center gap-2">
        <label
          htmlFor={inputId}
          className={`inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-border px-2.5 text-xs font-medium hover:bg-surface-muted ${
            uploading ? "pointer-events-none opacity-60" : ""
          }`}
        >
          <FileUp aria-hidden className="size-3.5" />
          {uploading ? "Mengunggah…" : "Unggah berkas"}
        </label>
        <input
          id={inputId}
          type="file"
          className="sr-only"
          accept={status.accepted_files}
          disabled={uploading}
          onChange={(e) => {
            void upload(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <span className="text-xs text-muted">
          {status.accepted_files} · maks. {status.upload_max_mb} MB
        </span>
      </div>
      <p className="flex items-start gap-1.5 text-xs text-muted">
        <ScanText aria-hidden className="mt-0.5 size-3.5 shrink-0" />
        {status.ocr.available
          ? `OCR tersedia (${status.ocr.message}) — halaman hasil scan dan gambar dibaca dengan OCR.`
          : status.ocr.message}
      </p>
      <Field label="Dokumen sumber proyek">
        {(a) => (
          <Select
            value={selectedId ?? ""}
            onChange={(e) => onSelect(documents.data?.find((d) => d.id === e.target.value) ?? null)}
            disabled={documents.isPending || !documents.data?.length}
            {...a}
          >
            <option value="">{documents.data?.length ? "Pilih dokumen…" : "Belum ada dokumen diunggah"}</option>
            {documents.data?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.filename} · {formatBytes(d.size_bytes)} · {formatTanggalWaktu(d.created_at)}
              </option>
            ))}
          </Select>
        )}
      </Field>
      {documents.isError && <p className="text-xs text-danger">{errorMessage(documents.error)}</p>}
      {selected && (
        <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
          Diunggah {selected.uploaded_by.full_name}.
          <a
            href={sourceDocumentFileUrl(selected.id)}
            className="inline-flex items-center gap-1 text-primary hover:underline"
          >
            <Download aria-hidden className="size-3" />
            Unduh asli
          </a>
        </p>
      )}
      {!selected && documents.data && documents.data.length > 0 && (
        <Button size="sm" variant="ghost" onClick={() => onSelect(documents.data[0] ?? null)}>
          Pakai dokumen terbaru
        </Button>
      )}
    </div>
  );
}
