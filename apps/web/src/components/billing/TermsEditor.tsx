"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { FormError, Input, Select } from "@/components/ui/Field";
import { ApiError, errorMessage } from "@/lib/api";
import type { PaymentTerm, TermBasis } from "@/lib/types";
import { normalizeDecimal } from "@/lib/forms";

export type TermRow = {
  name: string;
  basis: TermBasis;
  value: string;
  due_date: string;
  description: string;
};

const VALUE = /^\d{1,18}(\.\d{1,2})?$/;

export const PRESETS: { label: string; rows: TermRow[] }[] = [
  { label: "100%", rows: [row("Pembayaran penuh", "100")] },
  { label: "50/50", rows: [row("Uang muka", "50"), row("Pelunasan", "50")] },
  { label: "30/40/30", rows: [row("Uang muka", "30"), row("Termin 2", "40"), row("Pelunasan", "30")] },
];

function row(name: string, value: string): TermRow {
  return { name, basis: "percent", value, due_date: "", description: "" };
}

export function rowsFrom(terms: PaymentTerm[]): TermRow[] {
  return terms.map((t) => ({
    name: t.name,
    basis: t.basis,
    value: t.basis === "percent" ? trim(t.percent ?? "") : trim(t.amount),
    due_date: t.due_date ?? "",
    description: t.description ?? "",
  }));
}

function trim(value: string): string {
  return value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
}

/** Client-side checks for quick feedback; the server computes amounts and has the final say. */
export function validateRows(rows: TermRow[]): string | null {
  if (rows.length === 0) return "Tambahkan minimal satu termin.";
  for (const [index, r] of rows.entries()) {
    if (!r.name.trim()) return `Termin ${index + 1}: nama wajib diisi.`;
    const value = normalizeDecimal(r.value);
    if (!VALUE.test(value) || Number(value) <= 0) {
      return `Termin ${index + 1}: nilai harus angka > 0, mis. 30, 1500000, atau 1.500.000 (maks. 2 desimal).`;
    }
    if (r.basis === "percent" && Number(value) > 100) return `Termin ${index + 1}: persentase maks. 100.`;
  }
  return null;
}

export function termsPayload(rows: TermRow[]) {
  return rows.map((r) => ({
    name: r.name.trim(),
    basis: r.basis,
    value: normalizeDecimal(r.value),
    due_date: r.due_date || null,
    description: r.description.trim() || null,
  }));
}

export function TermsEditor({
  initial,
  onSave,
  onCancel,
}: {
  initial: TermRow[];
  onSave: (payload: ReturnType<typeof termsPayload>) => Promise<unknown>;
  onCancel?: () => void;
}) {
  const [rows, setRows] = useState<TermRow[]>(initial.length ? initial : PRESETS[2].rows);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (index: number, patch: Partial<TermRow>) =>
    setRows((current) => current.map((r, i) => (i === index ? { ...r, ...patch } : r)));

  const save = async () => {
    const problem = validateRows(rows);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSave(termsPayload(rows));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <FormError message={error} />
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <span>Isi cepat:</span>
        {PRESETS.map((preset) => (
          <Button key={preset.label} size="sm" variant="secondary" onClick={() => setRows(preset.rows.map((r) => ({ ...r })))}>
            {preset.label}
          </Button>
        ))}
      </div>
      <p className="text-xs text-muted">
        Persentase dihitung dari nilai sebelum pajak; termin bernilai tetap juga sebelum pajak. Pajak
        dibagi proporsional. Semua persen harus berjumlah 100%, dan campuran nilai tetap harus tepat
        sama dengan nilai sebelum pajak.
      </p>
      <div className="space-y-2">
        {rows.map((r, index) => (
          <fieldset key={index} className="grid gap-2 rounded-md border border-border p-2 sm:grid-cols-12" aria-label={`Termin ${index + 1}`}>
            <Input aria-label={`Nama termin ${index + 1}`} className="sm:col-span-3" value={r.name} maxLength={100} onChange={(e) => update(index, { name: e.target.value })} />
            <Select aria-label={`Jenis termin ${index + 1}`} className="sm:col-span-2" value={r.basis} onChange={(e) => update(index, { basis: e.target.value as TermBasis })}>
              <option value="percent">Persen</option>
              <option value="amount">Nilai tetap</option>
            </Select>
            <Input
              aria-label={r.basis === "percent" ? `Persen termin ${index + 1}` : `Nilai termin ${index + 1}`}
              className="tabular sm:col-span-2"
              inputMode="decimal"
              placeholder={r.basis === "percent" ? "30" : "1000000"}
              value={r.value}
              onChange={(e) => update(index, { value: e.target.value })}
            />
            <Input aria-label={`Jatuh tempo termin ${index + 1}`} className="sm:col-span-2" type="date" value={r.due_date} onChange={(e) => update(index, { due_date: e.target.value })} />
            <Input aria-label={`Keterangan termin ${index + 1}`} className="sm:col-span-2" placeholder="Keterangan" maxLength={500} value={r.description} onChange={(e) => update(index, { description: e.target.value })} />
            <Button variant="ghost" size="sm" aria-label={`Hapus termin ${index + 1}`} onClick={() => setRows((current) => current.filter((_, i) => i !== index))}>
              <Trash2 className="size-4" />
            </Button>
          </fieldset>
        ))}
      </div>
      <div className="flex flex-wrap justify-between gap-2">
        <Button size="sm" variant="secondary" disabled={rows.length >= 20} onClick={() => setRows((current) => [...current, row("", "")])}>
          <Plus aria-hidden className="size-4" />
          Tambah termin
        </Button>
        <div className="flex gap-2">
          {onCancel && (
            <Button size="sm" variant="secondary" onClick={onCancel} disabled={busy}>
              Batal
            </Button>
          )}
          <Button size="sm" loading={busy} onClick={() => void save()}>
            Simpan jadwal
          </Button>
        </div>
      </div>
    </div>
  );
}
