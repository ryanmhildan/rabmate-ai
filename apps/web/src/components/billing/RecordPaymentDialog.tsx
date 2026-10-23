"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, FormError, Input, Select, Textarea } from "@/components/ui/Field";
import { apiFetch } from "@/lib/api";
import { formatMoney, todayIso } from "@/lib/format";
import { applyServerErrors, normalizeDecimal, optionalText } from "@/lib/forms";
import { PAYMENT_METHOD, options } from "@/lib/labels";
import type { Invoice, Payment, PaymentMethod } from "@/lib/types";

const METHODS = Object.keys(PAYMENT_METHOD) as [PaymentMethod, ...PaymentMethod[]];

export const paymentSchema = z.object({
  amount: z
    .string()
    .trim()
    .transform(normalizeDecimal)
    .refine((v) => /^\d{1,18}(\.\d{1,2})?$/.test(v), "Tulis angka seperti 1500000, 1.500.000, atau 1.500.000,50.")
    .refine((v) => /[1-9]/.test(v), "Jumlah harus lebih dari 0."),
  payment_date: z
    .string()
    .min(1, "Tanggal wajib diisi.")
    .refine((v) => v <= todayIso(), "Tanggal pembayaran tidak boleh di masa depan."),
  method: z.enum(METHODS),
  reference: optionalText(200),
  notes: optionalText(10_000),
});
export type PaymentValues = z.infer<typeof paymentSchema>;

/** Payload for POST /payments: the whole amount is allocated to this invoice. */
export function paymentPayload(invoice: Pick<Invoice, "id" | "client" | "currency">, values: PaymentValues) {
  return {
    client_id: invoice.client.id,
    payment_date: values.payment_date,
    amount: values.amount.trim(),
    currency: invoice.currency,
    method: values.method,
    reference: values.reference.trim() || null,
    notes: values.notes.trim() || null,
    allocations: [{ invoice_id: invoice.id, amount: values.amount.trim() }],
  };
}

function trimZeros(value: string): string {
  return value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
}

type Props = {
  invoice: Invoice | null;
  onClose: () => void;
  onRecorded: (payment: Payment) => void;
};

export function RecordPaymentDialog({ invoice, onClose, onRecorded }: Props) {
  return (
    <Dialog open={invoice !== null} onClose={onClose} title="Catat pembayaran">
      {invoice && <PaymentForm invoice={invoice} onClose={onClose} onRecorded={onRecorded} />}
    </Dialog>
  );
}

function PaymentForm({ invoice, onClose, onRecorded }: { invoice: Invoice } & Omit<Props, "invoice">) {
  // One key per opening of the dialog: resubmitting after a timeout cannot record it twice.
  const [key] = useState(() => `pay-${crypto.randomUUID()}`);
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<PaymentValues>({
    resolver: zodResolver(paymentSchema),
    defaultValues: {
      amount: trimZeros(invoice.outstanding),
      payment_date: todayIso(),
      method: "transfer",
      reference: "",
      notes: "",
    },
  });

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const payment = await apiFetch<Payment>("/payments", {
        method: "POST",
        json: paymentPayload(invoice, values),
        headers: { "Idempotency-Key": key },
      });
      onRecorded(payment);
      onClose();
    } catch (error) {
      setFormError(applyServerErrors(error, setError, Object.keys(paymentSchema.shape)));
    }
  });

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormError message={formError} />
      <p className="text-sm text-muted">
        Invoice <strong className="text-foreground">{invoice.number}</strong> · sisa tagihan{" "}
        <strong className="tabular text-foreground">{formatMoney(invoice.outstanding, invoice.currency)}</strong>. Catat
        hanya pembayaran yang benar-benar diterima (sesuai bukti transfer/kuitansi).
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={`Jumlah (${invoice.currency})`} error={errors.amount?.message} required>
          {(a) => <Input inputMode="decimal" className="tabular" autoFocus {...a} {...register("amount")} />}
        </Field>
        <Field label="Tanggal diterima" error={errors.payment_date?.message} required>
          {(a) => <Input type="date" max={todayIso()} {...a} {...register("payment_date")} />}
        </Field>
        <Field label="Metode" error={errors.method?.message}>
          {(a) => (
            <Select {...a} {...register("method")}>
              {options(PAYMENT_METHOD).map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Referensi" error={errors.reference?.message} hint="No. bukti transfer, kuitansi, cek…">
          {(a) => <Input {...a} {...register("reference")} />}
        </Field>
        <Field label="Catatan" error={errors.notes?.message} className="sm:col-span-2">
          {(a) => <Textarea rows={2} {...a} {...register("notes")} />}
        </Field>
      </div>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
          Batal
        </Button>
        <Button type="submit" loading={isSubmitting}>
          Catat pembayaran
        </Button>
      </div>
    </form>
  );
}
