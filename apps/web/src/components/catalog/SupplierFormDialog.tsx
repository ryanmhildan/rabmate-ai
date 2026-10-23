"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, FormError, Input, Textarea } from "@/components/ui/Field";
import { api } from "@/lib/api";
import { applyServerErrors, blankToNull, optionalEmail, optionalText, phone } from "@/lib/forms";
import type { Supplier } from "@/lib/types";

const schema = z.object({
  name: z.string().trim().min(1, "Nama supplier wajib diisi.").max(200),
  contact_person: optionalText(200),
  phone,
  email: optionalEmail,
  city: optionalText(100),
  address: optionalText(5000),
  notes: optionalText(5000),
  is_active: z.boolean(),
});
type Values = z.infer<typeof schema>;

type Props = { open: boolean; supplier: Supplier | null; onClose: () => void };

export function SupplierFormDialog({ open, supplier, onClose }: Props) {
  return (
    <Dialog open={open} onClose={onClose} title={supplier ? "Ubah supplier" : "Tambah supplier"}>
      {open && <SupplierForm key={supplier?.id ?? "new"} supplier={supplier} onClose={onClose} />}
    </Dialog>
  );
}

function SupplierForm({ supplier, onClose }: Omit<Props, "open">) {
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: supplier?.name ?? "",
      contact_person: supplier?.contact_person ?? "",
      phone: supplier?.phone ?? "",
      email: supplier?.email ?? "",
      city: supplier?.city ?? "",
      address: supplier?.address ?? "",
      notes: supplier?.notes ?? "",
      is_active: supplier?.is_active ?? true,
    },
  });

  const submit = handleSubmit(async ({ is_active, ...values }) => {
    setFormError(null);
    try {
      const body = blankToNull(values);
      const saved = supplier
        ? await api.patch<Supplier>(`/suppliers/${supplier.id}`, { ...body, is_active, version: supplier.version })
        : await api.post<Supplier>("/suppliers", body);
      void queryClient.invalidateQueries({ queryKey: ["suppliers"] });
      toast.success(`Supplier ${saved.name} disimpan.`);
      onClose();
    } catch (error) {
      setFormError(applyServerErrors(error, setError, Object.keys(schema.shape)));
    }
  });

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormError message={formError} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Nama" error={errors.name?.message} required className="sm:col-span-2">
          {(a) => <Input autoFocus {...a} {...register("name")} />}
        </Field>
        <Field label="Kontak" error={errors.contact_person?.message}>
          {(a) => <Input {...a} {...register("contact_person")} />}
        </Field>
        <Field label="Telepon" error={errors.phone?.message}>
          {(a) => <Input type="tel" {...a} {...register("phone")} />}
        </Field>
        <Field label="Email" error={errors.email?.message}>
          {(a) => <Input type="email" {...a} {...register("email")} />}
        </Field>
        <Field label="Kota" error={errors.city?.message}>
          {(a) => <Input {...a} {...register("city")} />}
        </Field>
        <Field label="Alamat" error={errors.address?.message} className="sm:col-span-2">
          {(a) => <Textarea rows={2} {...a} {...register("address")} />}
        </Field>
        <Field label="Catatan" error={errors.notes?.message} className="sm:col-span-2">
          {(a) => <Textarea rows={2} {...a} {...register("notes")} />}
        </Field>
        {supplier && (
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input type="checkbox" className="size-4 accent-primary" {...register("is_active")} />
            Supplier aktif
          </label>
        )}
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
