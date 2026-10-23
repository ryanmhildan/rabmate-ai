"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ComponentProps } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field, FormError, Input, Textarea } from "@/components/ui/Field";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { applyServerErrors, blankToNull, optionalText } from "@/lib/forms";
import type { DocumentSettings } from "@/lib/types";

export const documentSettingsSchema = z.object({
  tagline: optionalText(200),
  accent_color: z
    .string()
    .trim()
    .regex(/^#[0-9A-Fa-f]{6}$/, "Gunakan format warna #RRGGBB."),
  footer_text: optionalText(500),
  rab_terms: z.string().max(5000, "Maksimal 5000 karakter."),
  show_item_codes: z.boolean(),
  show_price_sources: z.boolean(),
  show_amount_in_words: z.boolean(),
  payment_bank_name: optionalText(100),
  payment_account_number: z
    .string()
    .trim()
    .refine((v) => !v || /^[0-9][0-9 .-]{2,48}[0-9]$/.test(v), "Hanya angka (spasi, titik, tanda hubung boleh)."),
  payment_account_holder: optionalText(200),
  spk_terms: z.string().max(5000, "Maksimal 5000 karakter."),
  bast_terms: z.string().max(5000, "Maksimal 5000 karakter."),
});
export type DocumentSettingsValues = z.infer<typeof documentSettingsSchema>;
const FIELDS = Object.keys(documentSettingsSchema.shape);

function toValues(s: DocumentSettings): DocumentSettingsValues {
  return {
    tagline: s.tagline ?? "",
    accent_color: s.accent_color,
    footer_text: s.footer_text ?? "",
    rab_terms: s.rab_terms ?? "",
    show_item_codes: s.show_item_codes,
    show_price_sources: s.show_price_sources,
    show_amount_in_words: s.show_amount_in_words,
    payment_bank_name: s.payment_bank_name ?? "",
    payment_account_number: s.payment_account_number ?? "",
    payment_account_holder: s.payment_account_holder ?? "",
    spk_terms: s.spk_terms ?? "",
    bast_terms: s.bast_terms ?? "",
  };
}

export function DocumentSettingsPanel() {
  const settings = useQuery({
    queryKey: ["document-settings"],
    queryFn: ({ signal }) => api.get<DocumentSettings>("/document-settings", { signal }),
  });
  if (settings.isPending) return <p className="text-sm text-muted">Memuat template…</p>;
  if (settings.isError) return <p className="text-sm text-danger">{errorMessage(settings.error)}</p>;
  return <DocumentSettingsForm key={settings.data.version} settings={settings.data} />;
}

export function DocumentSettingsForm({ settings }: { settings: DocumentSettings }) {
  const canEdit = useCan("org.update");
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    control,
    handleSubmit,
    setError,
    setValue,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<DocumentSettingsValues>({
    resolver: zodResolver(documentSettingsSchema),
    defaultValues: toValues(settings),
  });
  const accent = useWatch({ control, name: "accent_color" });

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const saved = await api.put<DocumentSettings>("/document-settings", {
        ...blankToNull(values),
        version: settings.version,
      });
      queryClient.setQueryData(["document-settings"], saved);
      toast.success("Template dokumen disimpan.");
    } catch (error) {
      if (error instanceof ApiError && error.code === "version_conflict") {
        void queryClient.invalidateQueries({ queryKey: ["document-settings"] });
      }
      setFormError(applyServerErrors(error, setError, FIELDS));
    }
  });

  return (
    <form onSubmit={submit} noValidate className="space-y-5">
      <FormError message={formError} />
      <p className="text-sm text-muted">
        Nama, alamat, kontak, dan NPWP perusahaan diambil dari <strong>Profil perusahaan</strong>.
        Kolom yang kosong tidak dicetak — tidak ada data yang dikarang. Perubahan template tidak
        mengubah dokumen yang sudah terbit.
      </p>
      <fieldset disabled={!canEdit} className="space-y-5">
        <Card title="Kop & tampilan">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Tagline" error={errors.tagline?.message} className="sm:col-span-2">
              {(a) => <Input {...a} {...register("tagline")} />}
            </Field>
            <Field label="Warna aksen" error={errors.accent_color?.message}>
              {(a) => (
                <div className="flex items-center gap-2">
                  <input
                    type="color"
                    aria-label="Pilih warna aksen"
                    value={/^#[0-9A-Fa-f]{6}$/.test(accent) ? accent : "#1F4E79"}
                    onChange={(e) => setValue("accent_color", e.target.value.toUpperCase(), { shouldDirty: true })}
                    className="h-9 w-12 cursor-pointer rounded-md border border-border bg-surface"
                  />
                  <Input className="font-mono" {...a} {...register("accent_color")} />
                </div>
              )}
            </Field>
            <Field label="Teks kaki halaman" error={errors.footer_text?.message}>
              {(a) => <Input {...a} {...register("footer_text")} />}
            </Field>
          </div>
          <div className="space-y-2 text-sm">
            <Check label="Tampilkan kolom kode item" {...register("show_item_codes")} />
            <Check
              label="Tampilkan sumber harga (halaman mendatar)"
              {...register("show_price_sources")}
            />
            <Check label="Tampilkan terbilang untuk Rupiah" {...register("show_amount_in_words")} />
          </div>
        </Card>
        <Card title="Ketentuan RAB">
          <Field
            label="Ketentuan"
            error={errors.rab_terms?.message}
            hint="Dicetak di bawah total. Isi sendiri; aplikasi tidak menambahkan klausul hukum."
          >
            {(a) => <Textarea rows={5} {...a} {...register("rab_terms")} />}
          </Field>
        </Card>
        <Card title="Ketentuan SPK & BAST">
          <p className="text-xs text-muted">
            Disalin ke draft SPK/BAST baru dan masih dapat diubah per dokumen. Isi hanya ketentuan yang sudah disepakati;
            aplikasi tidak menambahkan klausul hukum atau kondisi serah terima.
          </p>
          <Field label="Ketentuan SPK" error={errors.spk_terms?.message}>
            {(a) => <Textarea rows={4} {...a} {...register("spk_terms")} />}
          </Field>
          <Field label="Ketentuan BAST" error={errors.bast_terms?.message}>
            {(a) => <Textarea rows={4} {...a} {...register("bast_terms")} />}
          </Field>
        </Card>
        <Card title="Informasi pembayaran">
          <p className="text-xs text-muted">Dicetak pada invoice sebagai tujuan pembayaran.</p>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Bank" error={errors.payment_bank_name?.message}>
              {(a) => <Input {...a} {...register("payment_bank_name")} />}
            </Field>
            <Field label="Nomor rekening" error={errors.payment_account_number?.message}>
              {(a) => <Input inputMode="numeric" {...a} {...register("payment_account_number")} />}
            </Field>
            <Field label="Atas nama" error={errors.payment_account_holder?.message}>
              {(a) => <Input {...a} {...register("payment_account_holder")} />}
            </Field>
          </div>
        </Card>
      </fieldset>
      {canEdit ? (
        <div className="flex justify-end">
          <Button type="submit" loading={isSubmitting} disabled={!isDirty}>
            Simpan template
          </Button>
        </div>
      ) : (
        <p className="text-sm text-muted">Hanya Owner/Admin yang dapat mengubah template dokumen.</p>
      )}
    </form>
  );
}

// React 19 passes `ref` as a prop, so register()'s ref reaches the input.
function Check({ label, ...input }: { label: string } & ComponentProps<"input">) {
  return (
    <label className="flex items-center gap-2">
      <input type="checkbox" className="size-4 accent-primary" {...input} />
      {label}
    </label>
  );
}
