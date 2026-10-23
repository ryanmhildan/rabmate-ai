"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, FormError, Input, Select } from "@/components/ui/Field";
import { api, queryString } from "@/lib/api";
import { applyServerErrors } from "@/lib/forms";
import type { Page, ProjectListItem, Rab } from "@/lib/types";

const schema = z.object({
  project_id: z.string().min(1, "Pilih proyek."),
  title: z.string().trim().min(1, "Judul wajib diisi.").max(200),
});
type Values = z.infer<typeof schema>;

type Props = {
  open: boolean;
  onClose: () => void;
  /** Preselects (and locks) the project, e.g. when opened from a project page. */
  project?: { id: string; label: string };
};

export function NewRabDialog({ open, onClose, project }: Props) {
  return (
    <Dialog open={open} onClose={onClose} title="RAB baru" description="Versi 1 dibuat sebagai draft.">
      {open && <NewRabForm onClose={onClose} project={project} />}
    </Dialog>
  );
}

function NewRabForm({ onClose, project }: Omit<Props, "open">) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { project_id: project?.id ?? "", title: "" },
  });

  // Only projects that accept new RAB (prospect, active, on hold).
  const projects = useQuery({
    queryKey: ["projects", "rab-options"],
    queryFn: async () => {
      const pages = await Promise.all(
        ["prospect", "active", "on_hold"].map((status) =>
          api.get<Page<ProjectListItem>>(
            `/projects${queryString({ status, page_size: 100, sort: "-updated_at" })}`,
          ),
        ),
      );
      return pages.flatMap((p) => p.items);
    },
    enabled: !project,
  });

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const rab = await api.post<Rab>(`/projects/${values.project_id}/rab`, { title: values.title });
      void queryClient.invalidateQueries({ queryKey: ["rab", "list"] });
      toast.success(`RAB ${rab.number} dibuat.`);
      onClose();
      router.push(`/rab/${rab.id}`);
    } catch (error) {
      setFormError(applyServerErrors(error, setError, ["title"]));
    }
  });

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <FormError message={formError} />
      {project ? (
        <p className="text-sm">
          Proyek: <strong>{project.label}</strong>
        </p>
      ) : (
        <Field
          label="Proyek"
          error={errors.project_id?.message}
          required
          hint={
            projects.data?.length === 0
              ? "Belum ada proyek berstatus prospek, berjalan, atau ditunda."
              : undefined
          }
        >
          {(a) => (
            <Select {...a} {...register("project_id")} disabled={projects.isPending}>
              <option value="">{projects.isPending ? "Memuat proyek…" : "— Pilih proyek —"}</option>
              {projects.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.number} — {p.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
      )}
      <Field label="Judul RAB" error={errors.title?.message} required hint="Mis. RAB Struktur Tahap 1">
        {(a) => <Input autoFocus {...a} {...register("title")} />}
      </Field>
      <p className="text-xs text-muted">Pajak awal mengikuti konfigurasi pajak proyek (bila ada).</p>
      <div className="flex justify-end gap-2 border-t border-border pt-4">
        <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
          Batal
        </Button>
        <Button type="submit" loading={isSubmitting}>
          Buat RAB
        </Button>
      </div>
    </form>
  );
}
