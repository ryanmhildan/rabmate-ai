"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, FormError, Input, Select, Textarea } from "@/components/ui/Field";
import { api } from "@/lib/api";
import { todayIso } from "@/lib/format";
import { applyServerErrors, blankToNull, decimalString, optionalText } from "@/lib/forms";
import type { Page, Supplier } from "@/lib/types";

const SOURCES = ["manual", "vendor_quote", "external"] as const;
const SOURCE_LABEL: Record<(typeof SOURCES)[number], string> = {
  manual: "Input manual / survei",
  vendor_quote: "Penawaran vendor",
  external: "Sumber eksternal (situs/marketplace)",
};

export const observationSchema = z
  .object({
    price: decimalString({ integerDigits: 16, fractionDigits: 4, label: "Harga" }).refine(
      (v) => v !== "",
      "Harga wajib diisi.",
    ),
    currency: z
      .string()
      .trim()
      .regex(/^[A-Z]{3}$/, "Kode 3 huruf kapital."),
    supplier_id: z.string(),
    source_type: z.enum(SOURCES),
    source_reference: optionalText(500),
    source_url: z
      .string()
      .trim()
      .refine((v) => v === "" || /^https?:\/\/\S+$/i.test(v), "Hanya URL http/https."),
    observed_at: z.string().min(1, "Tanggal wajib diisi."),
    valid_from: z.string(),
    valid_until: z.string(),
    location: optionalText(100),
    observed_specification: optionalText(5000),
    notes: optionalText(5000),
  })
  .superRefine((v, ctx) => {
    const start = v.valid_from || v.observed_at;
    if (v.valid_until && start && v.valid_until < start) {
      ctx.addIssue({ code: "custom", path: ["valid_until"], message: "Sebelum tanggal berlaku." });
    }
    if (v.source_type === "external" && !v.source_url) {
      ctx.addIssue({ code: "custom", path: ["source_url"], message: "Sumber eksternal wajib URL." });
    }
  });

export type ObservationValues = z.infer<typeof observationSchema>;

type Props = {
  open: boolean;
  unit: string;
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => Promise<unknown>;
};

export function ObservationFormDialog({ open, unit, onClose, onSubmit }: Props) {
  return (
    <Dialog open={open} onClose={onClose} title="Catat harga" description={`Satuan: ${unit}`} size="lg">
      {open && <ObservationForm onClose={onClose} onSubmit={onSubmit} />}
    </Dialog>
  );
}

function ObservationForm({ onClose, onSubmit }: Omit<Props, "open" | "unit">) {
  const [formError, setFormError] = useState<string | null>(null);
  const suppliers = useQuery({
    queryKey: ["suppliers", "options"],
    queryFn: () => api.get<Page<Supplier>>("/suppliers?is_active=true&page_size=100&sort=name"),
  });
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<ObservationValues>({
    resolver: zodResolver(observationSchema),
    defaultValues: {
      price: "",
      currency: "IDR",
      supplier_id: "",
      source_type: "manual",
      source_reference: "",
      source_url: "",
      observed_at: todayIso(),
      valid_from: "",
      valid_until: "",
      location: "",
      observed_specification: "",
      notes: "",
    },
  });

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await onSubmit(blankToNull(values));
      onClose();
    } catch (error) {
      setFormError(applyServerErrors(error, setError, Object.keys(observationSchema.shape)));
    }
  });

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormError message={formError} />
      <p className="text-sm text-muted">
        Harga baru selalu berstatus <strong>belum terverifikasi</strong>. Cantumkan supplier,
        referensi, atau URL agar dapat diverifikasi.
      </p>
      <div className="grid gap-4 sm:grid-cols-6">
        <Field label="Harga" error={errors.price?.message} required className="sm:col-span-3">
          {(a) => <Input autoFocus inputMode="decimal" className="tabular" {...a} {...register("price")} />}
        </Field>
        <Field label="Mata uang" error={errors.currency?.message} className="sm:col-span-1">
          {(a) => <Input maxLength={3} {...a} {...register("currency")} />}
        </Field>
        <Field label="Tanggal diperoleh" error={errors.observed_at?.message} required className="sm:col-span-2">
          {(a) => <Input type="date" {...a} {...register("observed_at")} />}
        </Field>
        <Field label="Jenis sumber" error={errors.source_type?.message} className="sm:col-span-3">
          {(a) => (
            <Select {...a} {...register("source_type")}>
              {SOURCES.map((s) => (
                <option key={s} value={s}>
                  {SOURCE_LABEL[s]}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Supplier" error={errors.supplier_id?.message} className="sm:col-span-3">
          {(a) => (
            <Select {...a} {...register("supplier_id")} disabled={suppliers.isPending}>
              <option value="">Tanpa supplier</option>
              {suppliers.data?.items.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field
          label="Referensi"
          error={errors.source_reference?.message}
          hint="Nomor penawaran, nota, atau keterangan survei."
          className="sm:col-span-3"
        >
          {(a) => <Input {...a} {...register("source_reference")} />}
        </Field>
        <Field label="URL sumber" error={errors.source_url?.message} className="sm:col-span-3">
          {(a) => <Input type="url" placeholder="https://" {...a} {...register("source_url")} />}
        </Field>
        <Field label="Berlaku mulai" error={errors.valid_from?.message} className="sm:col-span-2">
          {(a) => <Input type="date" {...a} {...register("valid_from")} />}
        </Field>
        <Field label="Berlaku sampai" error={errors.valid_until?.message} className="sm:col-span-2">
          {(a) => <Input type="date" {...a} {...register("valid_until")} />}
        </Field>
        <Field label="Lokasi pasar" error={errors.location?.message} className="sm:col-span-2">
          {(a) => <Input {...a} {...register("location")} />}
        </Field>
        <Field
          label="Spesifikasi menurut sumber"
          error={errors.observed_specification?.message}
          className="sm:col-span-6"
        >
          {(a) => <Textarea rows={2} {...a} {...register("observed_specification")} />}
        </Field>
        <Field label="Catatan" error={errors.notes?.message} className="sm:col-span-6">
          {(a) => <Textarea rows={2} {...a} {...register("notes")} />}
        </Field>
      </div>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
          Batal
        </Button>
        <Button type="submit" loading={isSubmitting}>
          Simpan harga
        </Button>
      </div>
    </form>
  );
}
