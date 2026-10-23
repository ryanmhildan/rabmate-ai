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
import { RAB_ITEM_TYPE, options } from "@/lib/labels";
import type { CatalogItem, Page, RabItemType, Supplier } from "@/lib/types";

const ITEM_TYPES = Object.keys(RAB_ITEM_TYPE) as [RabItemType, ...RabItemType[]];

export const catalogItemSchema = z
  .object({
    code: optionalText(50),
    name: z.string().trim().min(1, "Nama item wajib diisi.").max(300),
    category: optionalText(100),
    brand: optionalText(100),
    specification: optionalText(5000),
    unit: z.string().trim().min(1, "Satuan wajib diisi.").max(32),
    item_type: z.enum(ITEM_TYPES),
    notes: optionalText(5000),
    is_active: z.boolean(),
    // Optional first price (create only). Left blank → item is created without a price.
    price: decimalString({ integerDigits: 16, fractionDigits: 4, label: "Harga" }),
    observed_at: z.string(),
    supplier_id: z.string(),
    source_reference: optionalText(500),
    source_url: z
      .string()
      .trim()
      .refine((v) => v === "" || /^https?:\/\/\S+$/i.test(v), "Hanya URL http/https."),
  })
  .superRefine((v, ctx) => {
    if (v.price && !v.observed_at) {
      ctx.addIssue({ code: "custom", path: ["observed_at"], message: "Tanggal harga wajib diisi." });
    }
  });

export type CatalogItemValues = z.infer<typeof catalogItemSchema>;

/** Splits the form into the item body and, if a price was entered, its first observation. */
export function catalogItemPayload(values: CatalogItemValues, editing: boolean) {
  const { price, observed_at, supplier_id, source_reference, source_url, is_active, ...item } = values;
  const body: Record<string, unknown> = blankToNull(item);
  if (editing) return { ...body, is_active };
  if (price) {
    body.initial_price = blankToNull({
      price,
      currency: "IDR",
      observed_at,
      supplier_id,
      source_reference,
      source_url,
      source_type: "manual",
    });
  }
  return body;
}

type Props = {
  open: boolean;
  item: CatalogItem | null;
  /** The unit is fixed once prices are recorded against it (the API rejects the change). */
  unitLocked?: boolean;
  onClose: () => void;
  onSubmit: (payload: Record<string, unknown>) => Promise<unknown>;
};

export function CatalogItemFormDialog({ open, item, unitLocked = false, onClose, onSubmit }: Props) {
  return (
    <Dialog open={open} onClose={onClose} title={item ? "Ubah item katalog" : "Tambah item katalog"} size="lg">
      {open && (
        <CatalogItemForm
          key={item?.id ?? "new"}
          item={item}
          unitLocked={unitLocked}
          onClose={onClose}
          onSubmit={onSubmit}
        />
      )}
    </Dialog>
  );
}

function CatalogItemForm({ item, unitLocked, onClose, onSubmit }: Omit<Props, "open">) {
  const editing = item !== null;
  const [formError, setFormError] = useState<string | null>(null);
  const suppliers = useQuery({
    queryKey: ["suppliers", "options"],
    queryFn: () => api.get<Page<Supplier>>("/suppliers?is_active=true&page_size=100&sort=name"),
    enabled: !editing,
  });
  const categories = useQuery({
    queryKey: ["price-catalog", "categories"],
    queryFn: () => api.get<string[]>("/price-catalog/categories"),
  });
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<CatalogItemValues>({
    resolver: zodResolver(catalogItemSchema),
    defaultValues: {
      code: item?.code ?? "",
      name: item?.name ?? "",
      category: item?.category ?? "",
      brand: item?.brand ?? "",
      specification: item?.specification ?? "",
      unit: item?.unit ?? "",
      item_type: item?.item_type ?? "material",
      notes: item?.notes ?? "",
      is_active: item?.is_active ?? true,
      price: "",
      observed_at: todayIso(),
      supplier_id: "",
      source_reference: "",
      source_url: "",
    },
  });

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await onSubmit(catalogItemPayload(values, editing));
      onClose();
    } catch (error) {
      setFormError(applyServerErrors(error, setError, Object.keys(catalogItemSchema.shape)));
    }
  });

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormError message={formError} />
      <div className="grid gap-4 sm:grid-cols-6">
        <Field label="Nama item" error={errors.name?.message} required className="sm:col-span-4">
          {(a) => <Input autoFocus {...a} {...register("name")} />}
        </Field>
        <Field label="Kode" error={errors.code?.message} hint="Unik per organisasi." className="sm:col-span-2">
          {(a) => <Input {...a} {...register("code")} />}
        </Field>
        <Field label="Jenis" error={errors.item_type?.message} className="sm:col-span-2">
          {(a) => (
            <Select {...a} {...register("item_type")}>
              {options(RAB_ITEM_TYPE).map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Kategori" error={errors.category?.message} className="sm:col-span-2">
          {(a) => <Input list="catalog-categories" {...a} {...register("category")} />}
        </Field>
        <datalist id="catalog-categories">
          {categories.data?.map((c) => <option key={c} value={c} />)}
        </datalist>
        <Field
          label="Satuan"
          error={errors.unit?.message}
          required
          hint={unitLocked ? "Tidak dapat diubah: sudah ada riwayat harga." : "mis. m3, sak, unit, ls"}
          className="sm:col-span-2"
        >
          {(a) => <Input readOnly={unitLocked} {...a} {...register("unit")} />}
        </Field>
        <Field label="Merek" error={errors.brand?.message} className="sm:col-span-2">
          {(a) => <Input {...a} {...register("brand")} />}
        </Field>
        <Field label="Spesifikasi" error={errors.specification?.message} className="sm:col-span-4">
          {(a) => <Textarea rows={2} {...a} {...register("specification")} />}
        </Field>
        <Field label="Catatan" error={errors.notes?.message} className="sm:col-span-6">
          {(a) => <Textarea rows={2} {...a} {...register("notes")} />}
        </Field>
        {editing && (
          <label className="flex items-center gap-2 text-sm sm:col-span-6">
            <input type="checkbox" className="size-4 accent-primary" {...register("is_active")} />
            Item aktif (dapat dipakai sebagai kandidat harga)
          </label>
        )}
      </div>

      {!editing && (
        <fieldset className="space-y-3 rounded-md border border-border p-4">
          <legend className="px-1 text-sm font-medium">Harga awal (opsional)</legend>
          <p className="text-xs text-muted">
            Disimpan sebagai riwayat harga berstatus belum terverifikasi.
          </p>
          <div className="grid gap-4 sm:grid-cols-6">
            <Field label="Harga (IDR)" error={errors.price?.message} className="sm:col-span-3">
              {(a) => <Input inputMode="decimal" className="tabular" {...a} {...register("price")} />}
            </Field>
            <Field label="Tanggal harga" error={errors.observed_at?.message} className="sm:col-span-3">
              {(a) => <Input type="date" {...a} {...register("observed_at")} />}
            </Field>
            <Field label="Supplier" error={errors.supplier_id?.message} className="sm:col-span-3">
              {(a) => (
                <Select {...a} {...register("supplier_id")}>
                  <option value="">— Tanpa supplier —</option>
                  {suppliers.data?.items.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Referensi" error={errors.source_reference?.message} className="sm:col-span-3">
              {(a) => <Input {...a} {...register("source_reference")} />}
            </Field>
            <Field label="URL sumber" error={errors.source_url?.message} className="sm:col-span-6">
              {(a) => <Input type="url" placeholder="https://" {...a} {...register("source_url")} />}
            </Field>
          </div>
        </fieldset>
      )}

      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
          Batal
        </Button>
        <Button type="submit" loading={isSubmitting}>
          {editing ? "Simpan perubahan" : "Tambah item"}
        </Button>
      </div>
    </form>
  );
}
