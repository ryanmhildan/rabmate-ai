"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, FormError, Textarea } from "@/components/ui/Field";
import { errorMessage } from "@/lib/api";
import { formatUnitPrice } from "@/lib/format";
import type { PriceObservation } from "@/lib/types";

type Props = {
  target: { observation: PriceObservation; status: "verified" | "rejected" } | null;
  onClose: () => void;
  onConfirm: (status: "verified" | "rejected", note: string | null) => Promise<unknown>;
};

export function VerificationDialog({ target, onClose, onConfirm }: Props) {
  return (
    <Dialog
      open={target !== null}
      onClose={onClose}
      title={target?.status === "rejected" ? "Tolak harga" : "Verifikasi harga"}
    >
      {target && <VerificationForm key={`${target.observation.id}-${target.status}`} target={target} onClose={onClose} onConfirm={onConfirm} />}
    </Dialog>
  );
}

function VerificationForm({
  target,
  onClose,
  onConfirm,
}: {
  target: NonNullable<Props["target"]>;
  onClose: () => void;
  onConfirm: Props["onConfirm"];
}) {
  const { observation, status } = target;
  const reject = status === "rejected";
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasSource = Boolean(observation.supplier || observation.source_reference || observation.source_url);

  const confirm = async () => {
    if (reject && !note.trim()) {
      setError("Alasan penolakan wajib diisi.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onConfirm(status, note.trim() || null);
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
      <dl className="grid grid-cols-3 gap-2 rounded-md bg-surface-muted p-3 text-sm">
        <dt className="text-muted">Harga</dt>
        <dd className="tabular col-span-2">
          {formatUnitPrice(observation.price, observation.currency)} / {observation.unit}
        </dd>
        <dt className="text-muted">Sumber</dt>
        <dd className="col-span-2 break-words">
          {[observation.supplier?.name, observation.source_reference, observation.source_url]
            .filter(Boolean)
            .join(" · ") || <span className="text-danger">Tidak ada sumber</span>}
        </dd>
      </dl>
      {!reject && !hasSource && (
        <p className="text-sm text-danger">
          Harga tanpa sumber tidak dapat diverifikasi. Catat ulang harga dengan supplier, referensi,
          atau URL.
        </p>
      )}
      <Field label={reject ? "Alasan penolakan" : "Catatan verifikasi (opsional)"} required={reject}>
        {(a) => (
          <Textarea rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} {...a} />
        )}
      </Field>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Batal
        </Button>
        <Button
          variant={reject ? "danger" : "primary"}
          loading={busy}
          disabled={!reject && !hasSource}
          onClick={() => void confirm()}
        >
          {reject ? "Tolak" : "Verifikasi"}
        </Button>
      </div>
    </div>
  );
}
