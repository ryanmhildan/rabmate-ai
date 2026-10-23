"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
import { Field, FormError, Input, Textarea } from "@/components/ui/Field";
import { api, errorMessage } from "@/lib/api";
import { ME_QUERY_KEY, useCan } from "@/lib/auth";
import { applyServerErrors, blankToNull, npwp, optionalEmail, optionalText, phone } from "@/lib/forms";
import type { Organization } from "@/lib/types";

const schema = z.object({
  name: z.string().trim().min(1, "Nama organisasi wajib diisi.").max(200),
  legal_name: optionalText(200),
  tax_id: npwp,
  email: optionalEmail,
  phone,
  website: optionalText(200),
  city: optionalText(100),
  address: optionalText(5000),
});
type Values = z.infer<typeof schema>;
const FIELDS = Object.keys(schema.shape);

export function OrganizationSettings() {
  const org = useQuery({
    queryKey: ["organization"],
    queryFn: () => api.get<Organization>("/organizations/current"),
  });
  if (org.isPending) return <p className="text-sm text-muted">Memuat profil perusahaan…</p>;
  if (org.isError) return <FormError message={errorMessage(org.error)} />;
  return <OrganizationForm key={org.data.updated_at} organization={org.data} />;
}

function OrganizationForm({ organization }: { organization: Organization }) {
  const canEdit = useCan("org.update");
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: organization.name,
      legal_name: organization.legal_name ?? "",
      tax_id: organization.tax_id ?? "",
      email: organization.email ?? "",
      phone: organization.phone ?? "",
      website: organization.website ?? "",
      city: organization.city ?? "",
      address: organization.address ?? "",
    },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const saved = await api.patch<Organization>("/organizations/current", blankToNull(values));
      queryClient.setQueryData(["organization"], saved);
      void queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
      toast.success("Profil perusahaan disimpan.");
    } catch (error) {
      setFormError(applyServerErrors(error, setError, FIELDS));
    }
  });

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <p className="text-sm text-muted">
        Identitas ini dipakai pada dokumen (RAB, penawaran, invoice). Jangan isi data legal yang
        belum pasti.
      </p>
      <FormError message={formError} />
      <fieldset disabled={!canEdit} className="grid gap-4 sm:grid-cols-2">
        <Field label="Nama tampilan" error={errors.name?.message} required>
          {(a) => <Input {...a} {...register("name")} />}
        </Field>
        <Field label="Nama badan usaha" error={errors.legal_name?.message}>
          {(a) => <Input {...a} {...register("legal_name")} />}
        </Field>
        <Field label="NPWP" error={errors.tax_id?.message}>
          {(a) => <Input inputMode="numeric" {...a} {...register("tax_id")} />}
        </Field>
        <Field label="Email" error={errors.email?.message}>
          {(a) => <Input type="email" {...a} {...register("email")} />}
        </Field>
        <Field label="Telepon" error={errors.phone?.message}>
          {(a) => <Input type="tel" {...a} {...register("phone")} />}
        </Field>
        <Field label="Website" error={errors.website?.message}>
          {(a) => <Input {...a} {...register("website")} />}
        </Field>
        <Field label="Kota" error={errors.city?.message}>
          {(a) => <Input {...a} {...register("city")} />}
        </Field>
        <Field label="Alamat" error={errors.address?.message} className="sm:col-span-2">
          {(a) => <Textarea {...a} {...register("address")} />}
        </Field>
      </fieldset>
      {canEdit ? (
        <div className="flex justify-end">
          <Button type="submit" loading={isSubmitting} disabled={!isDirty}>
            Simpan profil
          </Button>
        </div>
      ) : (
        <p className="text-xs text-muted">Hanya Owner/Admin yang dapat mengubah profil perusahaan.</p>
      )}
    </form>
  );
}
