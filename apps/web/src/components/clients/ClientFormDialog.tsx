"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, FormError, Input, Select, Textarea } from "@/components/ui/Field";
import { api } from "@/lib/api";
import {
  applyServerErrors,
  blankToNull,
  npwp,
  optionalEmail,
  optionalText,
  phone,
} from "@/lib/forms";
import { CLIENT_TYPE, options } from "@/lib/labels";
import type { Client, ClientType } from "@/lib/types";

const schema = z.object({
  name: z.string().trim().min(1, "Nama klien wajib diisi.").max(200),
  code: z
    .string()
    .trim()
    .max(32)
    .regex(/^[A-Za-z0-9._-]*$/, "Kode hanya huruf, angka, titik, garis bawah, atau strip."),
  client_type: z.enum(["company", "individual", "government", "other"]),
  contact_person: optionalText(200),
  email: optionalEmail,
  phone,
  tax_id: npwp,
  city: optionalText(100),
  address: optionalText(5000),
  notes: optionalText(5000),
  is_active: z.boolean(),
});

export type ClientFormValues = z.infer<typeof schema>;
const FIELDS = Object.keys(schema.shape);

function toValues(client: Client | null): ClientFormValues {
  return {
    name: client?.name ?? "",
    code: client?.code ?? "",
    client_type: client?.client_type ?? ("company" satisfies ClientType),
    contact_person: client?.contact_person ?? "",
    email: client?.email ?? "",
    phone: client?.phone ?? "",
    tax_id: client?.tax_id ?? "",
    city: client?.city ?? "",
    address: client?.address ?? "",
    notes: client?.notes ?? "",
    is_active: client?.is_active ?? true,
  };
}

type Props = {
  /** null = create; a client = edit. */
  client: Client | null;
  open: boolean;
  onClose: () => void;
};

export function ClientFormDialog({ client, open, onClose }: Props) {
  // Re-mount the form for each opened record so defaults always match it.
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={client ? "Ubah klien" : "Tambah klien"}
      size="lg"
    >
      {open && <ClientForm key={client?.id ?? "new"} client={client} onDone={onClose} />}
    </Dialog>
  );
}

function ClientForm({ client, onDone }: { client: Client | null; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<ClientFormValues>({ resolver: zodResolver(schema), defaultValues: toValues(client) });

  const save = useMutation({
    mutationFn: ({ is_active, ...values }: ClientFormValues) => {
      const body = blankToNull(values);
      return client
        ? api.patch<Client>(`/clients/${client.id}`, { ...body, is_active, version: client.version })
        : api.post<Client>("/clients", body);
    },
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: ["clients"] });
      toast.success(client ? `Klien ${saved.name} diperbarui.` : `Klien ${saved.name} ditambahkan.`);
      onDone();
    },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await save.mutateAsync(values);
    } catch (error) {
      setFormError(applyServerErrors(error, setError, FIELDS));
    }
  });

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <FormError message={formError} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Nama klien" error={errors.name?.message} required className="sm:col-span-2">
          {(a) => <Input {...a} {...register("name")} />}
        </Field>
        <Field label="Kode" error={errors.code?.message} hint="Opsional, unik per organisasi.">
          {(a) => <Input {...a} {...register("code")} />}
        </Field>
        <Field label="Jenis" error={errors.client_type?.message}>
          {(a) => (
            <Select {...a} {...register("client_type")}>
              {options(CLIENT_TYPE).map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Kontak" error={errors.contact_person?.message}>
          {(a) => <Input {...a} {...register("contact_person")} />}
        </Field>
        <Field label="Email" error={errors.email?.message}>
          {(a) => <Input type="email" {...a} {...register("email")} />}
        </Field>
        <Field label="Telepon" error={errors.phone?.message}>
          {(a) => <Input type="tel" {...a} {...register("phone")} />}
        </Field>
        <Field label="NPWP" error={errors.tax_id?.message}>
          {(a) => <Input inputMode="numeric" {...a} {...register("tax_id")} />}
        </Field>
        <Field label="Kota" error={errors.city?.message}>
          {(a) => <Input {...a} {...register("city")} />}
        </Field>
        <Field label="Alamat" error={errors.address?.message} className="sm:col-span-2">
          {(a) => <Textarea {...a} {...register("address")} />}
        </Field>
        <Field label="Catatan" error={errors.notes?.message} className="sm:col-span-2">
          {(a) => <Textarea {...a} {...register("notes")} />}
        </Field>
        {client && (
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input type="checkbox" className="size-4 accent-primary" {...register("is_active")} />
            Klien aktif (klien nonaktif tidak muncul sebagai pilihan proyek baru)
          </label>
        )}
      </div>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" onClick={onDone} disabled={isSubmitting}>
          Batal
        </Button>
        <Button type="submit" loading={isSubmitting}>
          {client ? "Simpan perubahan" : "Tambah klien"}
        </Button>
      </div>
    </form>
  );
}
