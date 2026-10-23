"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { FormError } from "@/components/ui/Field";
import { ApiError, apiFetch, errorMessage } from "@/lib/api";
import { newIdempotencyKey } from "@/lib/documents";
import type { IssuedDocument } from "@/lib/types";

const DEFAULT_POINTS = [
  "Data saat ini dibekukan sebagai snapshot; berkas dibuat sekali dan disimpan.",
  "Perubahan data, profil perusahaan, atau template berikutnya tidak mengubah dokumen ini.",
  "Dokumen terbit tidak dapat diubah, hanya dibatalkan dengan alasan.",
];

type Props = {
  open: boolean;
  /** API path that issues the document, e.g. `/rab/{id}/versions/{n}/documents`. */
  endpoint: string;
  title: string;
  summary: ReactNode;
  points?: string[];
  onClose: () => void;
  onIssued: (document: IssuedDocument) => void;
};

export function IssueDocumentDialog(props: Props) {
  return (
    <Dialog open={props.open} onClose={props.onClose} title={props.title}>
      {/* Remounted per opening: each attempt gets its own idempotency key. */}
      {props.open && <IssueForm {...props} />}
    </Dialog>
  );
}

function IssueForm({ endpoint, summary, points = DEFAULT_POINTS, onClose, onIssued }: Props) {
  // One key for this attempt: a retry after a timeout or double click returns the same document.
  const [key] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [existingId, setExistingId] = useState<string | null>(null);

  const issue = async () => {
    setBusy(true);
    setError(null);
    try {
      const document = await apiFetch<IssuedDocument>(endpoint, {
        method: "POST",
        headers: { "Idempotency-Key": key },
      });
      onIssued(document);
      onClose();
    } catch (caught) {
      setError(errorMessage(caught));
      if (caught instanceof ApiError && caught.code === "already_issued") {
        const details = caught.details as { document_id?: string } | null;
        setExistingId(details?.document_id ?? null);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4 text-sm">
      <FormError message={error} />
      {existingId && (
        <Link href={`/dokumen/${existingId}`} className="text-primary hover:underline">
          Lihat dokumen yang sudah terbit
        </Link>
      )}
      <div>{summary}</div>
      <ul className="list-disc space-y-1 pl-5 text-muted">
        {points.map((point) => (
          <li key={point}>{point}</li>
        ))}
      </ul>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Batal
        </Button>
        <Button loading={busy} onClick={() => void issue()}>
          Terbitkan
        </Button>
      </div>
    </div>
  );
}
