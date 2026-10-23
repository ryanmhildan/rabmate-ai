"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, FormError, Input, Select } from "@/components/ui/Field";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { SkeletonRows, Table, TableMessage, Td, Th } from "@/components/ui/Table";
import { api, errorMessage } from "@/lib/api";
import { useCan, useMe } from "@/lib/auth";
import { formatTanggalWaktu } from "@/lib/format";
import { applyServerErrors } from "@/lib/forms";
import type { Member, Role, RoleInfo } from "@/lib/types";

const COLUMNS = 4;

export function UsersPanel() {
  const me = useMe();
  const canManage = useCan("users.manage");
  const queryClient = useQueryClient();
  const [adding, setAdding] = useState(false);

  const users = useQuery({ queryKey: ["users"], queryFn: () => api.get<Member[]>("/users") });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => api.get<RoleInfo[]>("/roles") });

  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: string; role?: Role; is_active?: boolean }) =>
      api.patch<Member>(`/users/${id}`, body),
    onSuccess: (member) => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      toast.success(`${member.full_name} diperbarui. Pengguna perlu masuk ulang.`);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted">
          Perubahan role atau status langsung mencabut sesi pengguna tersebut.
        </p>
        {canManage && (
          <Button onClick={() => setAdding(true)}>
            <Plus aria-hidden className="size-4" />
            Tambah pengguna
          </Button>
        )}
      </div>
      <Table label="Pengguna organisasi">
        <thead>
          <tr>
            <Th>Pengguna</Th>
            <Th>Role</Th>
            <Th>Status</Th>
            <Th>Terakhir masuk</Th>
          </tr>
        </thead>
        <tbody>
          {users.isPending && <SkeletonRows columns={COLUMNS} rows={3} />}
          {users.isError && (
            <TableMessage columns={COLUMNS}>
              <span className="text-danger">{errorMessage(users.error)}</span>
            </TableMessage>
          )}
          {users.data?.map((user) => {
            const self = user.id === me.user.id;
            return (
              <tr key={user.id}>
                <Td>
                  <div className="font-medium">
                    {user.full_name}
                    {self && <span className="ml-1 text-xs text-muted">(Anda)</span>}
                  </div>
                  <div className="text-xs text-muted">{user.email}</div>
                </Td>
                <Td>
                  {canManage && roles.data ? (
                    <Select
                      aria-label={`Role ${user.full_name}`}
                      value={user.role}
                      disabled={update.isPending}
                      onChange={(event) => update.mutate({ id: user.id, role: event.target.value as Role })}
                      className="w-44"
                    >
                      {roles.data.map((r) => (
                        <option key={r.role} value={r.role}>
                          {r.label}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    user.role_label
                  )}
                </Td>
                <Td>
                  <div className="flex items-center gap-2">
                    <StatusBadge tone={user.is_active ? "success" : "neutral"}>
                      {user.is_active ? "Aktif" : "Nonaktif"}
                    </StatusBadge>
                    {canManage && !self && (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={update.isPending}
                        onClick={() => update.mutate({ id: user.id, is_active: !user.is_active })}
                      >
                        {user.is_active ? "Nonaktifkan" : "Aktifkan"}
                      </Button>
                    )}
                  </div>
                </Td>
                <Td className="text-xs text-muted">
                  {user.last_login_at ? formatTanggalWaktu(user.last_login_at) : "Belum pernah"}
                </Td>
              </tr>
            );
          })}
        </tbody>
      </Table>
      {roles.data && <RoleMatrix roles={roles.data} />}
      <Dialog open={adding} onClose={() => setAdding(false)} title="Tambah pengguna">
        {adding && roles.data && <AddUserForm roles={roles.data} onDone={() => setAdding(false)} />}
      </Dialog>
    </div>
  );
}

const addSchema = z.object({
  email: z.string().trim().min(1, "Email wajib diisi.").email("Format email tidak valid."),
  full_name: z.string().trim().min(1, "Nama wajib diisi.").max(200),
  role: z.enum(["owner", "project_manager", "estimator", "finance", "approver", "viewer"]),
  password: z
    .string()
    .refine((v) => v === "" || (v.length >= 10 && v.length <= 128), "Kata sandi 10–128 karakter."),
});
type AddValues = z.infer<typeof addSchema>;

function AddUserForm({ roles, onDone }: { roles: RoleInfo[]; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<AddValues>({
    resolver: zodResolver(addSchema),
    defaultValues: { email: "", full_name: "", role: "viewer", password: "" },
  });

  const onSubmit = handleSubmit(async ({ password, ...values }) => {
    setFormError(null);
    try {
      const member = await api.post<Member>("/users", { ...values, password: password || null });
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      toast.success(`${member.full_name} ditambahkan sebagai ${member.role_label}.`);
      onDone();
    } catch (error) {
      setFormError(applyServerErrors(error, setError, Object.keys(addSchema.shape)));
    }
  });

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4">
      <FormError message={formError} />
      <Field label="Email" error={errors.email?.message} required>
        {(a) => <Input type="email" autoComplete="off" {...a} {...register("email")} />}
      </Field>
      <Field label="Nama lengkap" error={errors.full_name?.message} required>
        {(a) => <Input {...a} {...register("full_name")} />}
      </Field>
      <Field label="Role" error={errors.role?.message} required>
        {(a) => (
          <Select {...a} {...register("role")}>
            {roles.map((r) => (
              <option key={r.role} value={r.role}>
                {r.label}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field
        label="Kata sandi awal"
        error={errors.password?.message}
        hint="Wajib untuk pengguna baru (min. 10 karakter). Kosongkan bila email sudah terdaftar di organisasi lain."
      >
        {(a) => <Input type="password" autoComplete="new-password" {...a} {...register("password")} />}
      </Field>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" onClick={onDone} disabled={isSubmitting}>
          Batal
        </Button>
        <Button type="submit" loading={isSubmitting}>
          Tambah
        </Button>
      </div>
    </form>
  );
}

function RoleMatrix({ roles }: { roles: RoleInfo[] }) {
  return (
    <details className="rounded-lg border border-border bg-surface p-4 text-sm">
      <summary className="cursor-pointer font-medium">Izin setiap role</summary>
      <dl className="mt-3 space-y-2">
        {roles.map((r) => (
          <div key={r.role}>
            <dt className="font-medium">{r.label}</dt>
            <dd className="text-xs break-words text-muted">{r.permissions.join(", ")}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
