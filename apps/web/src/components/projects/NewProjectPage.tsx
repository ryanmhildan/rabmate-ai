"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/PageHeader";
import { api } from "@/lib/api";
import { useCan } from "@/lib/auth";
import type { Project } from "@/lib/types";
import { ProjectForm } from "./ProjectForm";

export function NewProjectPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const canWrite = useCan("projects.write");

  if (!canWrite) {
    return (
      <PageHeader title="Proyek baru" description="Anda tidak memiliki izin untuk membuat proyek." />
    );
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <PageHeader title="Proyek baru" description="Field bertanda * wajib diisi." />
      <ProjectForm
        project={null}
        submitLabel="Buat proyek"
        onCancel={() => router.push("/proyek")}
        onSubmit={async (payload) => {
          const project = await api.post<Project>("/projects", payload);
          void queryClient.invalidateQueries({ queryKey: ["projects"] });
          toast.success(`Proyek ${project.number} dibuat.`);
          router.push(`/proyek/${project.id}`);
        }}
      />
    </div>
  );
}
