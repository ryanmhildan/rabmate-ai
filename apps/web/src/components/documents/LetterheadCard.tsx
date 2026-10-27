"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ImageUp, Trash2 } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";
import { Button, buttonClass } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { FormError } from "@/components/ui/Field";
import { API_BASE, api, apiFetch, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { formatBytes } from "@/lib/documents";
import { formatTanggalWaktu } from "@/lib/format";
import type { Letterhead } from "@/lib/types";

export const LETTERHEAD_KEY = ["document-settings", "letterhead"] as const;
export const LETTERHEAD_MAX_BYTES = 2 * 1024 * 1024;
const ACCEPT = "image/png,image/jpeg,.png,.jpg,.jpeg";

/** Client-side checks before an upload (the server decodes the image and checks again). */
export function letterheadProblem(file: File): string | null {
  if (file.size === 0) return "File kosong.";
  if (file.size > LETTERHEAD_MAX_BYTES) return "Ukuran file kop surat melebihi 2 MB.";
  const name = file.name.toLowerCase();
  if (![".png", ".jpg", ".jpeg"].some((ext) => name.endsWith(ext))) {
    return "Format tidak didukung. Unggah gambar PNG atau JPEG.";
  }
  return null;
}

export function LetterheadCard() {
  const canEdit = useCan("org.update");
  const queryClient = useQueryClient();
  const inputId = useId();
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const letterhead = useQuery({
    queryKey: LETTERHEAD_KEY,
    queryFn: ({ signal }) => api.get<Letterhead | null>("/document-settings/letterhead", { signal }),
  });
  const current = letterhead.data ?? null;

  const upload = async (file: File | undefined) => {
    if (!file) return;
    const problem = letterheadProblem(file);
    setError(problem);
    if (problem) return;
    setUploading(true);
    try {
      const body = new FormData();
      body.append("file", file);
      const saved = await apiFetch<Letterhead>("/document-settings/letterhead", { method: "PUT", body });
      queryClient.setQueryData(LETTERHEAD_KEY, saved);
      toast.success("Kop surat disimpan. PDF berikutnya memakai kop ini.");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setUploading(false);
    }
  };

  const remove = async () => {
    setDeleting(true);
    try {
      await api.delete("/document-settings/letterhead");
      queryClient.setQueryData(LETTERHEAD_KEY, null);
      setConfirming(false);
      toast.success("Kop surat dihapus. PDF kembali memakai kop teks.");
    } catch (caught) {
      setConfirming(false);
      setError(errorMessage(caught));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Card title="Kop surat">
      <FormError message={error} />
      {letterhead.isPending ? (
        <div aria-hidden className="h-24 animate-pulse rounded-md bg-surface-muted" />
      ) : letterhead.isError ? (
        <p className="text-sm text-danger">{errorMessage(letterhead.error)}</p>
      ) : current ? (
        <figure className="space-y-2">
          {/* A paper-white frame in both themes: the kop is designed for print. */}
          <div className="rounded-md border border-border bg-white p-3">
            {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image, not a static asset */}
            <img
              src={`${API_BASE}/document-settings/letterhead/image?v=${current.sha256.slice(0, 16)}`}
              alt="Kop surat yang dipakai di PDF"
              width={current.width_px}
              height={current.height_px}
              className="mx-auto h-auto max-h-48 w-auto max-w-full"
            />
          </div>
          <figcaption className="text-xs text-muted">
            {current.filename} · {current.width_px} × {current.height_px} px · {formatBytes(current.size_bytes)}
            {" · "}diunggah {formatTanggalWaktu(current.uploaded_at)}
            {current.uploaded_by ? ` oleh ${current.uploaded_by.full_name}` : ""}
          </figcaption>
        </figure>
      ) : (
        <p className="rounded-md border border-dashed border-border px-3 py-4 text-sm text-muted">
          Belum ada kop surat. PDF memakai kop teks dari Profil perusahaan.
        </p>
      )}

      <p className="text-xs text-muted">
        PNG atau JPEG, maksimal 2 MB, lebar minimal 600 piksel dan lebih lebar daripada tingginya. Kop
        dicetak selebar halaman di halaman pertama setiap PDF (RAB, penawaran, invoice, SPK, BAST) dan
        menggantikan nama, alamat, kontak, NPWP, serta tagline, jadi pastikan data itu sudah ada di
        gambar. Dokumen yang sudah terbit tidak berubah.
      </p>

      {canEdit ? (
        <div className="flex flex-wrap items-center gap-2">
          {/* The input comes first so its keyboard focus can ring the visible label (peer). */}
          <input
            id={inputId}
            type="file"
            accept={ACCEPT}
            className="peer sr-only"
            disabled={uploading || deleting}
            onChange={(event) => {
              void upload(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
          <label
            htmlFor={inputId}
            className={buttonClass({
              variant: current ? "secondary" : "primary",
              className: `cursor-pointer peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-primary ${
                uploading || deleting ? "pointer-events-none opacity-60" : ""
              }`,
            })}
          >
            <ImageUp aria-hidden className="size-4" />
            {uploading ? "Mengunggah…" : current ? "Ganti kop" : "Unggah kop"}
          </label>
          {current && (
            <Button variant="ghost" onClick={() => setConfirming(true)} disabled={uploading || deleting}>
              <Trash2 aria-hidden className="size-4" />
              Hapus kop
            </Button>
          )}
        </div>
      ) : (
        <p className="text-sm text-muted">Hanya Owner/Admin yang dapat mengubah kop surat.</p>
      )}

      <ConfirmDialog
        open={confirming}
        title="Hapus kop surat?"
        message="PDF berikutnya kembali memakai kop teks dari Profil perusahaan. Dokumen yang sudah terbit tidak berubah."
        confirmLabel="Hapus kop"
        danger
        loading={deleting}
        onConfirm={() => void remove()}
        onClose={() => setConfirming(false)}
      />
    </Card>
  );
}
