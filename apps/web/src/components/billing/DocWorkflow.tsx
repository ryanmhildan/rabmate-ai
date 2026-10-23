"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Dialog } from "@/components/ui/Dialog";
import { Field, FormError, Textarea } from "@/components/ui/Field";
import { ApiError, api, errorMessage } from "@/lib/api";
import { formatTanggalWaktu } from "@/lib/format";
import { APPROVAL_ACTION, DOC_ACTION } from "@/lib/labels";
import type { ApprovalEntry, DocAction } from "@/lib/types";

/** Buttons for the actions the server says this user may take now (allowed_actions). */
export function WorkflowButtons<T>({
  base,
  actions,
  onDone,
}: {
  /** API path of the quotation/invoice, e.g. `/invoices/{id}`. */
  base: string;
  actions: DocAction[];
  onDone: (updated: T) => void;
}) {
  const [pending, setPending] = useState<DocAction | null>(null);
  return (
    <>
      {actions.map((action) => (
        <Button
          key={action}
          size="sm"
          variant={action === "approve" || action === "submit" ? "primary" : DOC_ACTION[action].danger ? "danger" : "secondary"}
          onClick={() => setPending(action)}
        >
          {DOC_ACTION[action].label}
        </Button>
      ))}
      <TransitionDialog<T> base={base} action={pending} onClose={() => setPending(null)} onDone={onDone} />
    </>
  );
}

export function TransitionDialog<T>({
  base,
  action,
  onClose,
  onDone,
}: {
  base: string;
  action: DocAction | null;
  onClose: () => void;
  onDone: (updated: T) => void;
}) {
  return (
    <Dialog open={action !== null} onClose={onClose} title={action ? DOC_ACTION[action].label : ""}>
      {action && <TransitionForm<T> key={action} base={base} action={action} onClose={onClose} onDone={onDone} />}
    </Dialog>
  );
}

function TransitionForm<T>({
  base,
  action,
  onClose,
  onDone,
}: {
  base: string;
  action: DocAction;
  onClose: () => void;
  onDone: (updated: T) => void;
}) {
  const required = Boolean(DOC_ACTION[action].noteRequired);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState<string[]>([]);

  const confirm = async () => {
    if (required && !note.trim()) {
      setError("Alasan wajib diisi.");
      return;
    }
    setBusy(true);
    setError(null);
    setDetails([]);
    try {
      onDone(await api.post<T>(`${base}/transitions/${action}`, { note: note.trim() || null }));
      onClose();
    } catch (caught) {
      setError(errorMessage(caught));
      setDetails(detailMessages(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <FormError message={error} />
      {details.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-sm text-danger">
          {details.map((message) => (
            <li key={message}>{message}</li>
          ))}
        </ul>
      )}
      <Field label={required ? "Alasan" : "Catatan (opsional)"} required={required}>
        {(a) => <Textarea rows={3} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} {...a} />}
      </Field>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Batal
        </Button>
        <Button variant={DOC_ACTION[action].danger ? "danger" : "primary"} loading={busy} onClick={() => void confirm()}>
          {DOC_ACTION[action].label}
        </Button>
      </div>
    </div>
  );
}

/** The per-field reasons of a refused transition (e.g. what must be filled in before review). */
export function detailMessages(error: unknown): string[] {
  if (!(error instanceof ApiError) || !Array.isArray(error.details)) return [];
  return (error.details as { msg?: unknown }[])
    .map((d) => (typeof d?.msg === "string" ? d.msg : null))
    .filter((m): m is string => Boolean(m));
}

export function ApprovalTimeline({ approvals }: { approvals: ApprovalEntry[] }) {
  return (
    <Card title="Riwayat persetujuan">
      {approvals.length === 0 ? (
        <p className="text-sm text-muted">Belum pernah diajukan.</p>
      ) : (
        <ol className="space-y-2 text-sm">
          {approvals.map((a, index) => (
            <li key={`${a.created_at}-${index}`}>
              <span className="font-medium">{a.actor?.full_name ?? "Sistem"}</span> {APPROVAL_ACTION[a.action]}
              <div className="text-xs text-muted">{formatTanggalWaktu(a.created_at)}</div>
              {a.note && <div className="text-xs text-muted">“{a.note}”</div>}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
