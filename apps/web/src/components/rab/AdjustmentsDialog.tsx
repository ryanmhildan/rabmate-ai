"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, FormError, Input, Select, Textarea } from "@/components/ui/Field";
import { applyServerErrors, blankToNull, moneyString, normalizeDecimal, optionalText, percentString } from "@/lib/forms";
import type { RabVersion } from "@/lib/types";
import { trimZeros } from "./ItemFormDialog";

const schema = z
  .object({
    tax_label: optionalText(32),
    tax_rate_percent: percentString,
    discount_type: z.enum(["none", "percent", "amount"]),
    discount_value: z.string().trim(),
    notes: optionalText(10_000),
    assumptions: optionalText(10_000),
  })
  .superRefine((v, ctx) => {
    if (Boolean(v.tax_label) !== Boolean(v.tax_rate_percent)) {
      ctx.addIssue({
        code: "custom",
        path: [v.tax_label ? "tax_rate_percent" : "tax_label"],
        message: "Label dan tarif pajak diisi bersamaan atau dikosongkan.",
      });
    }
    if (v.discount_type === "none") return;
    const check = (v.discount_type === "percent" ? percentString : moneyString).safeParse(
      v.discount_value,
    );
    if (!v.discount_value || !check.success) {
      ctx.addIssue({
        code: "custom",
        path: ["discount_value"],
        message:
          v.discount_type === "percent"
            ? "Persentase 0–100, maks. 2 desimal."
            : "Tulis nominal seperti 1500000 atau 1.500.000 (maks. 2 desimal).",
      });
    }
  });

type Values = z.infer<typeof schema>;
const FIELDS = Object.keys(schema.shape);

type Props = {
  open: boolean;
  version: RabVersion;
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => Promise<unknown>;
};

export function AdjustmentsDialog({ open, version, onClose, onSubmit }: Props) {
  return (
    <Dialog open={open} onClose={onClose} title="Pajak, diskon, dan catatan" size="lg">
      {open && <AdjustmentsForm key={version.lock_version} version={version} onClose={onClose} onSubmit={onSubmit} />}
    </Dialog>
  );
}

function AdjustmentsForm({ version, onClose, onSubmit }: Omit<Props, "open">) {
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    control,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      tax_label: version.tax_label ?? "",
      tax_rate_percent: version.tax_rate_percent ? trimZeros(version.tax_rate_percent) : "",
      discount_type: version.discount_type,
      discount_value: version.discount_type === "none" ? "" : trimZeros(version.discount_value),
      notes: version.notes ?? "",
      assumptions: version.assumptions ?? "",
    },
  });
  const discountType = useWatch({ control, name: "discount_type" });

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    const body = blankToNull(values);
    try {
      await onSubmit({
        ...body,
        discount_value: values.discount_type === "none" ? "0" : normalizeDecimal(values.discount_value),
        lock_version: version.lock_version,
      });
      onClose();
    } catch (error) {
      setFormError(applyServerErrors(error, setError, FIELDS));
    }
  });

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormError message={formError} />
      <p className="text-sm text-muted">
        Urutan hitung: subtotal − diskon = DPP; pajak dihitung dari DPP. Pajak hanya diterapkan bila
        label dan tarifnya diisi.
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Label pajak" error={errors.tax_label?.message} hint="Mis. PPN">
          {(a) => <Input {...a} {...register("tax_label")} />}
        </Field>
        <Field label="Tarif pajak (%)" error={errors.tax_rate_percent?.message}>
          {(a) => <Input inputMode="decimal" {...a} {...register("tax_rate_percent")} />}
        </Field>
        <Field label="Jenis diskon" error={errors.discount_type?.message}>
          {(a) => (
            <Select {...a} {...register("discount_type")}>
              <option value="none">Tanpa diskon</option>
              <option value="percent">Persentase (%)</option>
              <option value="amount">Nominal</option>
            </Select>
          )}
        </Field>
        <Field
          label={discountType === "percent" ? "Diskon (%)" : "Diskon (nominal)"}
          error={errors.discount_value?.message}
        >
          {(a) => (
            <Input inputMode="decimal" disabled={discountType === "none"} {...a} {...register("discount_value")} />
          )}
        </Field>
        <Field label="Catatan" error={errors.notes?.message} className="sm:col-span-2">
          {(a) => <Textarea rows={3} {...a} {...register("notes")} />}
        </Field>
        <Field
          label="Asumsi"
          error={errors.assumptions?.message}
          hint="Mis. harga belum termasuk ongkos kirim, berlaku 30 hari."
          className="sm:col-span-2"
        >
          {(a) => <Textarea rows={3} {...a} {...register("assumptions")} />}
        </Field>
      </div>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
          Batal
        </Button>
        <Button type="submit" loading={isSubmitting}>
          Simpan
        </Button>
      </div>
    </form>
  );
}
