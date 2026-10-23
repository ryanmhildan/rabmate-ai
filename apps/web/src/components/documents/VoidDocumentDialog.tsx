"use client";

import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, FormError, Textarea } from "@/components/ui/Field";
import { errorMessage } from "@/lib/api";

type Props = {
  /** Number of the thing being cancelled; null keeps the dialog closed. */
  number: string | null;
  title?: string;
  message?: ReactNode;
  confirmLabel?: string;
  onClose: () => void;
  onConfirm: (reason: string) => Promise<unknown>;
};

export function VoidDocumentDialog({ number, title = "Batalkan dokumen", ...rest }: Props) {
  return (
    <Dialog open={number !== null} onClose={rest.onClose} title={title}>
      {number !== null && <VoidForm number={number} {...rest} />}
    </Dialog>
  );
}

function VoidForm({
  number,
  message,
  confirmLabel = "Batalkan dokumen",
  onClose,
  onConfirm,
}: Omit<Props, "title"> & { number: string }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirm = async () => {
    if (!reason.trim()) {
      setError("Alasan pembatalan wajib diisi.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onConfirm(reason.trim());
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
      <div className="text-sm">
        {message ?? (
          <>
            Dokumen <strong>{number}</strong> akan ditandai <strong>dibatalkan</strong>. Berkas dan
            snapshot tetap tersimpan apa adanya sebagai arsip; versi RAB dapat diterbitkan ulang
            dengan nomor baru.
          </>
        )}
      </div>
      <Field label="Alasan pembatalan" required>
        {(a) => (
          <Textarea rows={3} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} {...a} />
        )}
      </Field>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Batal
        </Button>
        <Button variant="danger" loading={busy} onClick={() => void confirm()}>
          {confirmLabel}
        </Button>
      </div>
    </div>
  );
}
