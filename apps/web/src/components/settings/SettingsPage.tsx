"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { AuditList } from "@/components/audit/AuditList";
import { Button } from "@/components/ui/Button";
import { Field, FormError, Input } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { applyServerErrors } from "@/lib/forms";
import { DocumentSettingsPanel } from "@/components/documents/DocumentSettingsPanel";
import { OrganizationSettings } from "./OrganizationForm";
import { UsersPanel } from "./UsersPanel";

type Tab = "organisasi" | "template" | "pengguna" | "aktivitas" | "akun";

export function SettingsPage() {
  const canReadUsers = useCan("users.read");
  const canAudit = useCan("audit.read");
  const canReadDocuments = useCan("documents.read");
  const tabs: { id: Tab; label: string; visible: boolean }[] = [
    { id: "organisasi", label: "Profil perusahaan", visible: true },
    { id: "template", label: "Template dokumen", visible: canReadDocuments },
    { id: "pengguna", label: "Pengguna & role", visible: canReadUsers },
    { id: "aktivitas", label: "Log aktivitas", visible: canAudit },
    { id: "akun", label: "Akun saya", visible: true },
  ];
  const visible = tabs.filter((t) => t.visible);
  const [active, setActive] = useState<Tab>("organisasi");

  return (
    <div className="space-y-5">
      <PageHeader title="Pengaturan" description="Profil perusahaan, template dokumen, pengguna, dan keamanan akun." />
      <div role="tablist" aria-label="Bagian pengaturan" className="flex gap-1 overflow-x-auto overflow-y-hidden border-b border-border">
        {visible.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            type="button"
            id={`tab-${tab.id}`}
            aria-selected={active === tab.id}
            aria-controls={`panel-${tab.id}`}
            onClick={() => setActive(tab.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm whitespace-nowrap ${
              active === tab.id
                ? "border-primary font-medium text-primary"
                : "border-transparent text-muted hover:text-foreground"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`} className="max-w-4xl">
        {active === "organisasi" && <OrganizationSettings />}
        {active === "template" && <DocumentSettingsPanel />}
        {active === "pengguna" && <UsersPanel />}
        {active === "aktivitas" && <AuditList pageSize={20} />}
        {active === "akun" && <ChangePasswordForm />}
      </div>
    </div>
  );
}

const passwordSchema = z
  .object({
    current_password: z.string().min(1, "Wajib diisi."),
    new_password: z.string().min(10, "Minimal 10 karakter.").max(128),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, {
    path: ["confirm"],
    message: "Konfirmasi tidak sama.",
  });
type PasswordValues = z.infer<typeof passwordSchema>;

function ChangePasswordForm() {
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<PasswordValues>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { current_password: "", new_password: "", confirm: "" },
  });

  const onSubmit = handleSubmit(async ({ current_password, new_password }) => {
    setFormError(null);
    try {
      await api.post("/auth/change-password", { current_password, new_password });
      reset();
      toast.success("Kata sandi diganti. Sesi di perangkat lain telah dicabut.");
    } catch (error) {
      setFormError(applyServerErrors(error, setError, ["current_password", "new_password"]));
    }
  });

  return (
    <form onSubmit={onSubmit} noValidate className="max-w-sm space-y-4">
      <FormError message={formError} />
      <Field label="Kata sandi saat ini" error={errors.current_password?.message} required>
        {(a) => (
          <Input type="password" autoComplete="current-password" {...a} {...register("current_password")} />
        )}
      </Field>
      <Field label="Kata sandi baru" error={errors.new_password?.message} required hint="Minimal 10 karakter.">
        {(a) => <Input type="password" autoComplete="new-password" {...a} {...register("new_password")} />}
      </Field>
      <Field label="Ulangi kata sandi baru" error={errors.confirm?.message} required>
        {(a) => <Input type="password" autoComplete="new-password" {...a} {...register("confirm")} />}
      </Field>
      <Button type="submit" loading={isSubmitting}>
        Ganti kata sandi
      </Button>
    </form>
  );
}
