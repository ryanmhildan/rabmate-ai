"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, FormError, Textarea } from "@/components/ui/Field";
import { ApiError, errorMessage } from "@/lib/api";
import { RAB_ACTION } from "@/lib/labels";
import type { RabAction, RabIssue } from "@/lib/types";

type Props = {
  action: RabAction | null;
  versionNo: number;
  onClose: () => void;
  onConfirm: (action: RabAction, note: string | null) => Promise<unknown>;
};

/** Confirms a status change; collects the note and shows blocking validation issues. */
export function TransitionDialog({ action, versionNo, onClose, onConfirm }: Props) {
  return (
    <Dialog
      open={action !== null}
      onClose={onClose}
      title={action ? `${RAB_ACTION[action].label} (versi ${versionNo})` : ""}
    >
      {action && <TransitionForm key={action} action={action} onClose={onClose} onConfirm={onConfirm} />}
    </Dialog>
  );
}

function blockingIssues(error: unknown): RabIssue[] {
  if (!(error instanceof ApiError) || typeof error.details !== "object" || error.details === null) {
    return [];
  }
  const issues = (error.details as { issues?: unknown }).issues;
  return Array.isArray(issues) ? (issues as RabIssue[]).filter((i) => i.severity === "error") : [];
}

function TransitionForm({
  action,
  onClose,
  onConfirm,
}: {
  action: RabAction;
  onClose: () => void;
  onConfirm: Props["onConfirm"];
}) {
  const meta = RAB_ACTION[action];
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [noteError, setNoteError] = useState<string | null>(null);
  const issues = blockingIssues(error);

  const confirm = async () => {
    if (meta.noteRequired && !note.trim()) {
      setNoteError("Wajib diisi.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onConfirm(action, note.trim() || null);
      onClose();
    } catch (caught) {
      setError(caught);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      {error !== null && <FormError message={errorMessage(error)} />}
      {issues.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm text-danger">
          {issues.map((issue, index) => (
            <li key={`${issue.code}-${index}`}>{issue.message}</li>
          ))}
        </ul>
      )}
      <Field label={meta.noteLabel} error={noteError ?? undefined} required={meta.noteRequired}>
        {(a) => (
          <Textarea
            rows={3}
            maxLength={2000}
            value={note}
            onChange={(event) => {
              setNote(event.target.value);
              setNoteError(null);
            }}
            {...a}
          />
        )}
      </Field>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Batal
        </Button>
        <Button variant={meta.danger ? "danger" : "primary"} loading={busy} onClick={() => void confirm()}>
          {meta.label}
        </Button>
      </div>
    </div>
  );
}
