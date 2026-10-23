"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";
import { AuditList } from "@/components/audit/AuditList";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { FullPageMessage } from "@/components/ui/FullPageMessage";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { formatMoney, formatPercent, formatTanggal, formatTanggalWaktu } from "@/lib/format";
import { PROJECT_STATUS, PROJECT_TYPE } from "@/lib/labels";
import type { Project, ProjectStatus } from "@/lib/types";
import { ProjectForm } from "./ProjectForm";
import { ProjectRabSection } from "@/components/rab/ProjectRabSection";
import { ProjectMembers } from "./ProjectMembers";
import { ProjectChat } from "@/components/ai/ProjectChat";

export function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const canWrite = useCan("projects.write");
  const canDelete = useCan("projects.delete");
  const canAudit = useCan("audit.read");
  const canAskAi = useCan("ai.use");
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const queryKey = ["projects", "detail", id];

  const project = useQuery({
    queryKey,
    queryFn: ({ signal }) => api.get<Project>(`/projects/${id}`, { signal }),
    retry: false,
  });

  const onSaved = (saved: Project) => {
    queryClient.setQueryData(queryKey, saved);
    void queryClient.invalidateQueries({ queryKey: ["projects"], exact: false });
    void queryClient.invalidateQueries({ queryKey: ["audit"] });
  };

  const changeStatus = useMutation({
    mutationFn: (status: ProjectStatus) =>
      api.patch<Project>(`/projects/${id}`, { version: project.data?.version, status }),
    onSuccess: (saved) => {
      onSaved(saved);
      toast.success(`Status menjadi ${PROJECT_STATUS[saved.status].label}.`);
    },
    onError: (error) => {
      toast.error(errorMessage(error));
      if (error instanceof ApiError && error.code === "version_conflict") void project.refetch();
    },
  });

  const remove = useMutation({
    mutationFn: () => api.delete(`/projects/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      toast.success("Proyek dihapus.");
      router.replace("/proyek");
    },
    onError: (error) => {
      setConfirmDelete(false);
      toast.error(errorMessage(error));
    },
  });

  if (project.isPending) return <FullPageMessage loading title="Memuat proyek…" />;
  if (project.isError) {
    const notFound = project.error instanceof ApiError && project.error.status === 404;
    return (
      <div className="space-y-4">
        <BackLink />
        <PageHeader
          title={notFound ? "Proyek tidak ditemukan" : "Proyek gagal dimuat"}
          description={notFound ? "Proyek mungkin sudah dihapus." : errorMessage(project.error)}
        />
      </div>
    );
  }

  const p = project.data;

  if (editing) {
    return (
      <div className="mx-auto max-w-4xl space-y-5">
        <PageHeader title={`Ubah ${p.number}`} description={p.name} />
        <ProjectForm
          project={p}
          submitLabel="Simpan perubahan"
          onCancel={() => setEditing(false)}
          onSubmit={async (payload) => {
            try {
              const saved = await api.patch<Project>(`/projects/${id}`, { ...payload, version: p.version });
              onSaved(saved);
              toast.success("Perubahan disimpan.");
              setEditing(false);
            } catch (error) {
              if (error instanceof ApiError && error.code === "version_conflict") {
                void project.refetch();
              }
              throw error;
            }
          }}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <BackLink />
      <PageHeader
        title={p.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs">{p.number}</span>
            <StatusBadge tone={PROJECT_STATUS[p.status].tone}>{PROJECT_STATUS[p.status].label}</StatusBadge>
            <span>{PROJECT_TYPE[p.project_type]}</span>
          </span>
        }
        actions={
          <>
            {canWrite && (
              <Button variant="secondary" onClick={() => setEditing(true)}>
                <Pencil aria-hidden className="size-4" />
                Ubah
              </Button>
            )}
            {canDelete && (
              <Button variant="secondary" onClick={() => setConfirmDelete(true)}>
                <Trash2 aria-hidden className="size-4" />
                Hapus
              </Button>
            )}
          </>
        }
      />

      {canWrite && p.allowed_status_transitions.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface px-4 py-3 text-sm">
          <span className="text-muted">Ubah status:</span>
          {p.allowed_status_transitions.map((status) => (
            <Button
              key={status}
              variant="secondary"
              size="sm"
              loading={changeStatus.isPending && changeStatus.variables === status}
              disabled={changeStatus.isPending}
              onClick={() => changeStatus.mutate(status)}
            >
              {PROJECT_STATUS[status].label}
            </Button>
          ))}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="space-y-4 lg:col-span-2">
          <ProjectRabSection project={p} />
          {canAskAi && <ProjectChat projectId={p.id} />}
          <Card title="Ringkasan">
            <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
              <Item label="Klien">{p.client?.name ?? "—"}</Item>
              <Item label="Penanggung jawab">{p.owner?.full_name ?? "—"}</Item>
              <Item label="Lokasi">{p.location ?? "—"}</Item>
              <Item label="Jadwal">
                {p.start_date ? formatTanggal(p.start_date) : "—"}
                {p.end_date ? ` s.d. ${formatTanggal(p.end_date)}` : ""}
              </Item>
              <Item label="Anggaran">
                <span className="tabular">{formatMoney(p.budget_amount, p.currency)}</span>
              </Item>
              <Item label="Pajak">
                {p.tax_label ? `${p.tax_label} ${formatPercent(p.tax_rate_percent)}` : "Belum dikonfigurasi"}
              </Item>
            </dl>
          </Card>
          <Card title="Deskripsi & ruang lingkup">
            <Prose label="Deskripsi" text={p.description} />
            <Prose label="Ruang lingkup" text={p.scope} />
            <Prose label="Catatan" text={p.notes} />
          </Card>
          {Object.keys(p.attributes).length > 0 && (
            <Card title="Atribut tambahan">
              <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
                {Object.entries(p.attributes).map(([key, value]) => (
                  <Item key={key} label={key}>
                    {value === null ? "—" : String(value)}
                  </Item>
                ))}
              </dl>
            </Card>
          )}
        </section>
        <aside className="space-y-4">
          <ProjectMembers project={p} canEdit={canWrite} onSaved={onSaved} />
          <p className="text-xs text-muted">
            Dibuat {formatTanggalWaktu(p.created_at)} · diperbarui {formatTanggalWaktu(p.updated_at)}
          </p>
        </aside>
      </div>

      {canAudit && (
        <Card title="Aktivitas">
          <AuditList entityType="project" entityId={p.id} />
        </Card>
      )}

      <ConfirmDialog
        open={confirmDelete}
        title="Hapus proyek?"
        message={
          <>
            Proyek <strong>{p.number}</strong> akan dihapus permanen. Riwayat aktivitasnya tetap
            tersimpan di log audit.
          </>
        }
        confirmLabel="Hapus proyek"
        danger
        loading={remove.isPending}
        onConfirm={() => remove.mutate()}
        onClose={() => setConfirmDelete(false)}
      />
    </div>
  );
}

function BackLink() {
  return (
    <Link href="/proyek" className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground">
      <ArrowLeft aria-hidden className="size-4" />
      Kembali ke daftar proyek
    </Link>
  );
}

function Item({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  );
}

function Prose({ label, text }: { label: string; text: string | null }) {
  return (
    <div className="text-sm">
      <p className="text-xs text-muted">{label}</p>
      {/* Rendered as text (React escapes it); whitespace preserved for multi-line input. */}
      <p className="mt-0.5 whitespace-pre-wrap">{text ?? "—"}</p>
    </div>
  );
}
