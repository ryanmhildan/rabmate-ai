"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useFieldArray, useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
import { Field, FormError, Input, Select, Textarea } from "@/components/ui/Field";
import { api, queryString } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { formatRupiah } from "@/lib/format";
import { applyServerErrors, blankToNull, moneyString, optionalText, percentString } from "@/lib/forms";
import { PROJECT_TYPE, options } from "@/lib/labels";
import type { Client, Member, Page, Project, ProjectType } from "@/lib/types";

const ATTRIBUTE_KEY = /^[a-z][a-z0-9_]{0,49}$/;

const schema = z
  .object({
    number: z
      .string()
      .trim()
      .max(32)
      .regex(/^[A-Za-z0-9/._-]*$/, "Nomor hanya huruf, angka, / . _ -"),
    name: z.string().trim().min(1, "Nama proyek wajib diisi.").max(200),
    project_type: z.enum([
      "construction",
      "fabrication",
      "procurement",
      "it",
      "professional_services",
      "operations",
      "other",
    ]),
    client_id: z.string(),
    owner_id: z.string(),
    location: optionalText(200),
    start_date: z.string(),
    end_date: z.string(),
    currency: z
      .string()
      .trim()
      .regex(/^[A-Z]{3}$/, "Kode mata uang 3 huruf kapital (mis. IDR)."),
    budget_amount: moneyString,
    tax_label: optionalText(32),
    tax_rate_percent: percentString,
    description: optionalText(5000),
    scope: optionalText(5000),
    notes: optionalText(5000),
    attributes: z
      .array(
        z.object({
          key: z.string().trim().regex(ATTRIBUTE_KEY, "huruf kecil/angka/_ , diawali huruf"),
          value: z.string().max(500, "Maks. 500 karakter."),
        }),
      )
      .max(30, "Maksimal 30 atribut."),
  })
  .superRefine((values, ctx) => {
    if (values.start_date && values.end_date && values.end_date < values.start_date) {
      ctx.addIssue({
        code: "custom",
        path: ["end_date"],
        message: "Tanggal selesai tidak boleh sebelum tanggal mulai.",
      });
    }
    if (Boolean(values.tax_label) !== Boolean(values.tax_rate_percent)) {
      ctx.addIssue({
        code: "custom",
        path: [values.tax_label ? "tax_rate_percent" : "tax_label"],
        message: "Label dan tarif pajak diisi bersamaan atau dikosongkan.",
      });
    }
    const keys = values.attributes.map((a) => a.key);
    keys.forEach((key, index) => {
      if (keys.indexOf(key) !== index) {
        ctx.addIssue({ code: "custom", path: ["attributes", index, "key"], message: "Nama ganda." });
      }
    });
  });

type Values = z.infer<typeof schema>;
const FIELDS = Object.keys(schema.shape);

function toValues(project: Project | null): Values {
  return {
    number: project?.number ?? "",
    name: project?.name ?? "",
    project_type: project?.project_type ?? ("construction" satisfies ProjectType),
    client_id: project?.client?.id ?? "",
    owner_id: project?.owner?.id ?? "",
    location: project?.location ?? "",
    start_date: project?.start_date ?? "",
    end_date: project?.end_date ?? "",
    currency: project?.currency ?? "IDR",
    budget_amount: project?.budget_amount ?? "",
    tax_label: project?.tax_label ?? "",
    tax_rate_percent: project?.tax_rate_percent ?? "",
    description: project?.description ?? "",
    scope: project?.scope ?? "",
    notes: project?.notes ?? "",
    attributes: Object.entries(project?.attributes ?? {}).map(([key, value]) => ({
      key,
      value: value === null ? "" : String(value),
    })),
  };
}

/** Builds the API payload: blanks become null, attributes become an object of strings. */
export function toPayload(values: Values, isEdit: boolean) {
  const { attributes, number, ...rest } = values;
  return {
    ...blankToNull(rest),
    ...(isEdit ? {} : { number: number.trim() || null }),
    attributes: Object.fromEntries(attributes.map((a) => [a.key, a.value])),
  };
}

type Props = {
  project: Project | null;
  submitLabel: string;
  onSubmit: (payload: ReturnType<typeof toPayload>) => Promise<unknown>;
  onCancel: () => void;
};

export function ProjectForm({ project, submitLabel, onSubmit, onCancel }: Props) {
  const canReadUsers = useCan("users.read");
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    control,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: toValues(project) });
  const attributes = useFieldArray({ control, name: "attributes" });

  const clients = useQuery({
    queryKey: ["clients", "options"],
    queryFn: () =>
      api.get<Page<Client>>(`/clients${queryString({ is_active: true, page_size: 100, sort: "name" })}`),
  });
  const users = useQuery({
    queryKey: ["users"],
    queryFn: () => api.get<Member[]>("/users"),
    enabled: canReadUsers,
  });

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const payload: Partial<ReturnType<typeof toPayload>> = toPayload(values, project !== null);
      // Without users.read the owner picker is hidden; never clear an owner we could not show.
      if (!canReadUsers) delete payload.owner_id;
      await onSubmit(payload as ReturnType<typeof toPayload>);
    } catch (error) {
      setFormError(applyServerErrors(error, setError, FIELDS));
    }
  });

  const budget = useWatch({ control, name: "budget_amount" });
  const clientOptions = clients.data?.items ?? [];
  const currentClient = project?.client;

  return (
    <form onSubmit={submit} noValidate className="space-y-6">
      <FormError message={formError} />

      <section className="grid gap-4 rounded-lg border border-border bg-surface p-4 sm:grid-cols-2">
        <h2 className="text-sm font-semibold sm:col-span-2">Informasi utama</h2>
        <Field label="Nama proyek" error={errors.name?.message} required className="sm:col-span-2">
          {(a) => <Input {...a} {...register("name")} />}
        </Field>
        {!project && (
          <Field
            label="Nomor proyek"
            error={errors.number?.message}
            hint="Kosongkan untuk penomoran otomatis (PRJ-tahun-urut)."
          >
            {(a) => <Input {...a} {...register("number")} />}
          </Field>
        )}
        <Field label="Jenis proyek" error={errors.project_type?.message} required>
          {(a) => (
            <Select {...a} {...register("project_type")}>
              {options(PROJECT_TYPE).map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field
          label="Klien"
          error={errors.client_id?.message}
          hint={clients.isError ? "Daftar klien gagal dimuat." : undefined}
        >
          {(a) => (
            <Select {...a} {...register("client_id")} disabled={clients.isPending}>
              <option value="">Tanpa klien</option>
              {currentClient && !clientOptions.some((c) => c.id === currentClient.id) && (
                <option value={currentClient.id}>{currentClient.name}</option>
              )}
              {clientOptions.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {canReadUsers && (
          <Field label="Penanggung jawab" error={errors.owner_id?.message}>
            {(a) => (
              <Select {...a} {...register("owner_id")} disabled={users.isPending}>
                <option value="">Belum ditentukan</option>
                {(users.data ?? [])
                  .filter((u) => u.is_active || u.id === project?.owner?.id)
                  .map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name} ({u.role_label})
                    </option>
                  ))}
              </Select>
            )}
          </Field>
        )}
        <Field label="Lokasi" error={errors.location?.message} hint="Isi bila relevan.">
          {(a) => <Input {...a} {...register("location")} />}
        </Field>
        <Field label="Tanggal mulai" error={errors.start_date?.message}>
          {(a) => <Input type="date" {...a} {...register("start_date")} />}
        </Field>
        <Field label="Tanggal selesai" error={errors.end_date?.message}>
          {(a) => <Input type="date" {...a} {...register("end_date")} />}
        </Field>
      </section>

      <section className="grid gap-4 rounded-lg border border-border bg-surface p-4 sm:grid-cols-3">
        <h2 className="text-sm font-semibold sm:col-span-3">Anggaran & pajak</h2>
        <Field label="Mata uang" error={errors.currency?.message}>
          {(a) => <Input maxLength={3} {...a} {...register("currency")} />}
        </Field>
        <Field
          label="Anggaran"
          error={errors.budget_amount?.message}
          hint={budget && !errors.budget_amount ? formatRupiah(budget) : "Opsional, mis. 1.250.000.000"}
          className="sm:col-span-2"
        >
          {(a) => <Input inputMode="decimal" className="tabular" {...a} {...register("budget_amount")} />}
        </Field>
        <Field label="Label pajak" error={errors.tax_label?.message} hint="Mis. PPN">
          {(a) => <Input {...a} {...register("tax_label")} />}
        </Field>
        <Field
          label="Tarif pajak (%)"
          error={errors.tax_rate_percent?.message}
          hint="Hanya dipakai bila diisi; tidak ada pajak default."
        >
          {(a) => <Input inputMode="decimal" {...a} {...register("tax_rate_percent")} />}
        </Field>
      </section>

      <section className="grid gap-4 rounded-lg border border-border bg-surface p-4">
        <h2 className="text-sm font-semibold">Deskripsi & ruang lingkup</h2>
        <Field label="Deskripsi" error={errors.description?.message}>
          {(a) => <Textarea {...a} {...register("description")} />}
        </Field>
        <Field label="Ruang lingkup" error={errors.scope?.message}>
          {(a) => <Textarea rows={4} {...a} {...register("scope")} />}
        </Field>
        <Field label="Catatan" error={errors.notes?.message}>
          {(a) => <Textarea {...a} {...register("notes")} />}
        </Field>
      </section>

      <section className="space-y-3 rounded-lg border border-border bg-surface p-4">
        <div>
          <h2 className="text-sm font-semibold">Atribut tambahan</h2>
          <p className="text-xs text-muted">
            Field khusus jenis proyek, mis. <code>luas_bangunan_m2</code>, <code>material_utama</code>,{" "}
            <code>jumlah_unit</code>. Opsional.
          </p>
        </div>
        {attributes.fields.map((field, index) => (
          <div key={field.id} className="flex items-start gap-2">
            <Field
              label="Nama"
              error={errors.attributes?.[index]?.key?.message}
              className="w-2/5"
            >
              {(a) => <Input {...a} {...register(`attributes.${index}.key`)} />}
            </Field>
            <Field label="Nilai" error={errors.attributes?.[index]?.value?.message} className="flex-1">
              {(a) => <Input {...a} {...register(`attributes.${index}.value`)} />}
            </Field>
            <Button
              variant="ghost"
              size="sm"
              className="mt-6"
              aria-label="Hapus atribut"
              onClick={() => attributes.remove(index)}
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
        ))}
        {errors.attributes?.message && <p className="text-xs text-danger">{errors.attributes.message}</p>}
        <Button
          variant="secondary"
          size="sm"
          disabled={attributes.fields.length >= 30}
          onClick={() => attributes.append({ key: "", value: "" })}
        >
          <Plus aria-hidden className="size-4" />
          Tambah atribut
        </Button>
      </section>

      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onCancel} disabled={isSubmitting}>
          Batal
        </Button>
        <Button type="submit" loading={isSubmitting}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
