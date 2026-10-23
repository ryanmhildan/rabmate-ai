"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Link2Off, Search } from "lucide-react";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { type CandidateSearch, PriceCandidatesPanel } from "@/components/catalog/PriceCandidatesPanel";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, FormError, Input, Select, Textarea } from "@/components/ui/Field";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useCan } from "@/lib/auth";
import { formatUnitPrice } from "@/lib/format";
import { applyServerErrors, blankToNull, decimalString, optionalText } from "@/lib/forms";
import { PRICE_SOURCE_TYPE, RAB_ITEM_TYPE, VERIFICATION_STATUS, options } from "@/lib/labels";
import type { PriceCandidate, RabItem, VerificationStatus } from "@/lib/types";

const ITEM_TYPES = [
  "material",
  "labor",
  "service",
  "equipment",
  "transport",
  "overhead",
  "other",
] as const;
const SOURCE_TYPES = ["", "manual", "catalog", "history", "vendor_quote", "import", "external"] as const;

const schema = z
  .object({
    name: z.string().trim().min(1, "Nama item wajib diisi.").max(300),
    code: optionalText(50),
    category: optionalText(100),
    item_type: z.enum(ITEM_TYPES),
    specification: optionalText(10_000),
    quantity: decimalString({ integerDigits: 14, fractionDigits: 4, positive: true, label: "Kuantitas" }).refine(
      (v) => v !== "",
      "Kuantitas wajib diisi.",
    ),
    unit: z.string().trim().min(1, "Satuan wajib diisi.").max(32),
    unit_price: decimalString({ integerDigits: 16, fractionDigits: 4, label: "Harga satuan" }),
    price_source_type: z.enum(SOURCE_TYPES),
    price_source: optionalText(500),
    notes: optionalText(10_000),
    // Catalog price reference; when set the server takes price and source from it.
    price_observation_id: z.string(),
  })
  .superRefine((values, ctx) => {
    if (!values.unit_price && values.price_source_type) {
      ctx.addIssue({
        code: "custom",
        path: ["price_source_type"],
        message: "Isi harga satuan dulu, atau kosongkan jenis sumber.",
      });
    }
  });

export type ItemFormValues = z.infer<typeof schema>;
const FIELDS = Object.keys(schema.shape);

function toValues(item: RabItem | null): ItemFormValues {
  return {
    name: item?.name ?? "",
    code: item?.code ?? "",
    category: item?.category ?? "",
    item_type: item?.item_type ?? "material",
    specification: item?.specification ?? "",
    // Trailing zeros from NUMERIC(…,4) are noise in an input field.
    quantity: item ? trimZeros(item.quantity) : "",
    unit: item?.unit ?? "",
    unit_price: item?.unit_price ? trimZeros(item.unit_price) : "",
    price_source_type: item?.price_source_type ?? "",
    price_source: item?.price_source ?? "",
    notes: item?.notes ?? "",
    price_observation_id: item?.price_observation_id ?? "",
  };
}

/** What the form shows while an item is linked to a catalog price. */
type LinkedPrice = { price: string; unit: string; status: VerificationStatus | null; source: string };

function linkedFromItem(item: RabItem | null): LinkedPrice | null {
  if (!item?.price_observation_id || !item.unit_price) return null;
  return {
    price: item.unit_price,
    unit: item.unit,
    status: item.price_verification_status,
    source: item.price_source ?? "",
  };
}

export function trimZeros(value: string): string {
  return value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
}

/** API payload: blanks → null, decimals stay strings. */
export function itemPayload(values: ItemFormValues) {
  return blankToNull({ ...values }) as Record<string, string | null>;
}

type Props = {
  open: boolean;
  item: RabItem | null;
  /** RAB currency; price candidates are limited to it. */
  currency?: string;
  onClose: () => void;
  onSubmit: (payload: Record<string, string | null>) => Promise<unknown>;
};

export function ItemFormDialog({ open, item, currency = "IDR", onClose, onSubmit }: Props) {
  return (
    <Dialog open={open} onClose={onClose} title={item ? "Ubah item" : "Tambah item"} size="lg">
      {open && (
        <ItemForm key={item?.id ?? "new"} item={item} currency={currency} onClose={onClose} onSubmit={onSubmit} />
      )}
    </Dialog>
  );
}

type PriceFields = Pick<ItemFormValues, "price_observation_id" | "unit_price" | "price_source_type" | "price_source">;

function ItemForm({ item, currency = "IDR", onClose, onSubmit }: Omit<Props, "open">) {
  const canSearch = useCan("pricing.read");
  const [formError, setFormError] = useState<string | null>(null);
  const [linked, setLinked] = useState<LinkedPrice | null>(() => linkedFromItem(item));
  const [search, setSearch] = useState<CandidateSearch | null>(null);
  const {
    register,
    control,
    handleSubmit,
    setError,
    setValue,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<ItemFormValues>({ resolver: zodResolver(schema), defaultValues: toValues(item) });
  const unitPrice = useWatch({ control, name: "unit_price" });

  const setPrice = (values: PriceFields) => {
    const options = { shouldDirty: true, shouldValidate: true };
    setValue("price_observation_id", values.price_observation_id, options);
    setValue("unit_price", values.unit_price, options);
    setValue("price_source_type", values.price_source_type, options);
    setValue("price_source", values.price_source, options);
  };

  const startSearch = () => {
    const { name, unit, specification } = getValues();
    if (name.trim().length < 2) {
      setError("name", { type: "manual", message: "Isi nama item (min. 2 karakter) untuk mencari harga." });
      return;
    }
    setSearch({ name: name.trim(), unit: unit.trim(), specification: specification.trim(), currency });
  };

  const applyCandidate = (c: PriceCandidate) => {
    const price = trimZeros(c.price);
    if (c.kind === "catalog" && c.observation_id) {
      // Display only: the server re-reads the catalog price and writes the provenance itself.
      setPrice({
        price_observation_id: c.observation_id,
        unit_price: price,
        price_source_type: "catalog",
        price_source: `Katalog: ${c.name}`,
      });
      setLinked({
        price: c.price,
        unit: c.unit,
        status: c.verified ? "verified" : "unverified",
        source: [c.supplier, c.source_reference].filter(Boolean).join(" · "),
      });
    } else {
      setPrice({
        price_observation_id: "",
        unit_price: price,
        price_source_type: "history",
        price_source: c.reference ?? "Riwayat RAB",
      });
      setLinked(null);
    }
    setSearch(null);
  };

  const unlink = () => {
    setPrice({ price_observation_id: "", unit_price: "", price_source_type: "", price_source: "" });
    setLinked(null);
  };

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await onSubmit(itemPayload(values));
      onClose();
    } catch (error) {
      setFormError(applyServerErrors(error, setError, FIELDS));
    }
  });

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormError message={formError} />
      <div className="grid gap-4 sm:grid-cols-6">
        <Field label="Nama item" error={errors.name?.message} required className="sm:col-span-4">
          {(a) => <Input autoFocus {...a} {...register("name")} />}
        </Field>
        <Field label="Kode" error={errors.code?.message} className="sm:col-span-2">
          {(a) => <Input {...a} {...register("code")} />}
        </Field>
        <Field label="Jenis" error={errors.item_type?.message} className="sm:col-span-3">
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
        <Field label="Kategori" error={errors.category?.message} hint="Mis. Pekerjaan struktur" className="sm:col-span-3">
          {(a) => <Input {...a} {...register("category")} />}
        </Field>
        <Field label="Kuantitas" error={errors.quantity?.message} required className="sm:col-span-2">
          {(a) => <Input inputMode="decimal" className="tabular" {...a} {...register("quantity")} />}
        </Field>
        <Field label="Satuan" error={errors.unit?.message} required hint="Mis. m3, sak, OH, unit" className="sm:col-span-2">
          {(a) => <Input {...a} {...register("unit")} />}
        </Field>
        {linked ? (
          <LinkedPriceBox linked={linked} currency={currency} onUnlink={unlink} />
        ) : (
          <>
            <Field
              label="Harga satuan"
              error={errors.unit_price?.message}
              hint="Kosongkan bila belum diketahui (tidak dapat diajukan)."
              className="sm:col-span-2"
            >
              {(a) => <Input inputMode="decimal" className="tabular" {...a} {...register("unit_price")} />}
            </Field>
            <Field label="Jenis sumber harga" error={errors.price_source_type?.message} className="sm:col-span-2">
              {(a) => (
                <Select {...a} {...register("price_source_type")} disabled={!unitPrice}>
                  <option value="">—</option>
                  {options(PRICE_SOURCE_TYPE).map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field
              label="Sumber harga"
              error={errors.price_source?.message}
              hint="Nama toko/vendor, nomor penawaran, URL, atau tanggal survei."
              className="sm:col-span-4"
            >
              {(a) => <Input {...a} {...register("price_source")} />}
            </Field>
          </>
        )}
        {canSearch && (
          <div className="flex items-end sm:col-span-2">
            <Button variant="secondary" onClick={search ? () => setSearch(null) : startSearch} className="w-full">
              <Search aria-hidden className="size-4" />
              {search ? "Tutup pencarian" : "Cari harga"}
            </Button>
          </div>
        )}
        {search && (
          <div className="sm:col-span-6">
            <PriceCandidatesPanel search={search} onUse={applyCandidate} />
          </div>
        )}
        <Field label="Spesifikasi" error={errors.specification?.message} className="sm:col-span-6">
          {(a) => <Textarea rows={2} {...a} {...register("specification")} />}
        </Field>
        <Field label="Catatan" error={errors.notes?.message} className="sm:col-span-6">
          {(a) => <Textarea rows={2} {...a} {...register("notes")} />}
        </Field>
      </div>
      <p className="text-xs text-muted">Subtotal dihitung oleh server setelah disimpan.</p>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
          Batal
        </Button>
        <Button type="submit" loading={isSubmitting}>
          {item ? "Simpan item" : "Tambah item"}
        </Button>
      </div>
    </form>
  );
}

function LinkedPriceBox({
  linked,
  currency,
  onUnlink,
}: {
  linked: LinkedPrice;
  currency: string;
  onUnlink: () => void;
}) {
  const status = linked.status ? VERIFICATION_STATUS[linked.status] : null;
  return (
    <div className="rounded-md border border-primary/30 bg-primary/5 p-3 text-sm sm:col-span-6">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <div className="text-xs font-medium text-muted">Harga dari katalog (dikunci)</div>
          <div className="tabular font-medium">
            {formatUnitPrice(linked.price, currency)}{" "}
            <span className="text-xs font-normal text-muted">/ {linked.unit}</span>
          </div>
          {linked.source && <div className="text-xs break-words text-muted">{linked.source}</div>}
          {status && <StatusBadge tone={status.tone}>{status.label}</StatusBadge>}
        </div>
        <Button variant="ghost" size="sm" onClick={onUnlink}>
          <Link2Off aria-hidden className="size-4" />
          Lepas tautan
        </Button>
      </div>
      <p className="mt-2 text-xs text-muted">
        Harga dan sumber diambil server dari katalog saat disimpan. Satuan item harus sama dengan
        satuan katalog.
      </p>
    </div>
  );
}
