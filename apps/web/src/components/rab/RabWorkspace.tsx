"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Copy, GitCompare, Lock, Plus } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { FullPageMessage } from "@/components/ui/FullPageMessage";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { formatMoney, formatTanggalWaktu } from "@/lib/format";
import { RAB_ACTION, RAB_STATUS } from "@/lib/labels";
import type { Rab, RabAction, RabItem, RabVersion } from "@/lib/types";
import { AiAssistantCard } from "@/components/ai/AiAssistantCard";
import { RabDocumentsCard } from "@/components/documents/RabDocumentsCard";
import { AdjustmentsDialog } from "./AdjustmentsDialog";
import { ItemFormDialog } from "./ItemFormDialog";
import { ApprovalHistory, IssuesCard, ItemsTable, NotesCard, TotalsCard } from "./RabPanels";
import { TransitionDialog } from "./TransitionDialog";

export const rabKeys = {
  all: ["rab"] as const,
  detail: (id: string) => ["rab", id] as const,
  version: (id: string, versionNo: number) => ["rab", id, "version", versionNo] as const,
};

export function RabWorkspace() {
  const { id } = useParams<{ id: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const canWrite = useCan("rab.write");

  const rab = useQuery({
    queryKey: rabKeys.detail(id),
    queryFn: ({ signal }) => api.get<Rab>(`/rab/${id}`, { signal }),
    retry: false,
  });
  const latest = rab.data ? Math.max(...rab.data.versions.map((v) => v.version_no)) : null;
  const requested = Number(search.get("v"));
  const selected =
    rab.data && rab.data.versions.some((v) => v.version_no === requested) ? requested : latest;

  const version = useQuery({
    queryKey: rabKeys.version(id, selected ?? 0),
    queryFn: ({ signal }) => api.get<RabVersion>(`/rab/${id}/versions/${selected}`, { signal }),
    enabled: selected !== null,
  });

  const [itemDialog, setItemDialog] = useState<{ open: boolean; item: RabItem | null }>({
    open: false,
    item: null,
  });
  const [deleting, setDeleting] = useState<RabItem | null>(null);
  const [adjusting, setAdjusting] = useState(false);
  const [action, setAction] = useState<RabAction | null>(null);

  const showVersion = (versionNo: number) => router.replace(`/rab/${id}?v=${versionNo}`);

  /** Every mutation returns the full version; keep caches that show its status/totals fresh. */
  const applyVersion = (saved: RabVersion) => {
    queryClient.setQueryData(rabKeys.version(id, saved.version_no), saved);
    void queryClient.invalidateQueries({ queryKey: rabKeys.detail(id), exact: true });
    void queryClient.invalidateQueries({ queryKey: ["rab", "list"] });
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["approvals"] });
  };

  const onMutationError = (error: unknown) => {
    toast.error(errorMessage(error));
    if (error instanceof ApiError && (error.status === 409 || error.code === "version_conflict")) {
      void version.refetch();
      void rab.refetch();
    }
  };

  const base = `/rab/${id}/versions/${selected}`;

  const removeItem = useMutation({
    mutationFn: (item: RabItem) =>
      api.delete<RabVersion>(`${base}/items/${item.id}?row_version=${item.row_version}`),
    onSuccess: (saved, item) => {
      applyVersion(saved);
      toast.success(`${item.name} dihapus.`);
      setDeleting(null);
    },
    onError: (error) => {
      setDeleting(null);
      onMutationError(error);
    },
  });

  const newVersion = useMutation({
    mutationFn: () => api.post<RabVersion>(`/rab/${id}/versions`, { from_version_no: selected }),
    onSuccess: (saved) => {
      applyVersion(saved);
      toast.success(`Versi ${saved.version_no} dibuat dari versi ${selected}.`);
      showVersion(saved.version_no);
    },
    onError: onMutationError,
  });

  const duplicate = useMutation({
    mutationFn: () => api.post<Rab>(`/rab/${id}/duplicate`, { version_no: selected }),
    onSuccess: (copy) => {
      void queryClient.invalidateQueries({ queryKey: ["rab", "list"] });
      toast.success(`RAB ${copy.number} dibuat.`);
      router.push(`/rab/${copy.id}`);
    },
    onError: onMutationError,
  });

  if (rab.isPending) return <FullPageMessage loading title="Memuat RAB…" />;
  if (rab.isError) {
    const notFound = rab.error instanceof ApiError && rab.error.status === 404;
    return (
      <div className="space-y-4">
        <BackLink />
        <PageHeader
          title={notFound ? "RAB tidak ditemukan" : "RAB gagal dimuat"}
          description={notFound ? "RAB mungkin sudah dihapus." : errorMessage(rab.error)}
        />
      </div>
    );
  }

  const doc = rab.data;
  const v = version.data;

  return (
    <div className="space-y-5">
      <BackLink />
      <PageHeader
        title={doc.title}
        description={
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-mono text-xs">{doc.number}</span>
            <span>·</span>
            <Link href={`/proyek/${doc.project.id}`} className="text-primary hover:underline">
              {doc.project.number} {doc.project.name}
            </Link>
          </span>
        }
        actions={
          <>
            {doc.versions.length > 1 && (
              <Link
                href={compareHref(id, selected ?? 1)}
                className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-surface px-3.5 text-sm font-medium hover:bg-surface-muted"
              >
                <GitCompare aria-hidden className="size-4" />
                Bandingkan
              </Link>
            )}
            {canWrite && (
              <Button variant="secondary" loading={duplicate.isPending} onClick={() => duplicate.mutate()}>
                <Copy aria-hidden className="size-4" />
                Gandakan
              </Button>
            )}
          </>
        }
      />

      <nav aria-label="Versi RAB" className="flex flex-wrap gap-2">
        {doc.versions.map((summary) => (
          <button
            key={summary.id}
            type="button"
            aria-current={summary.version_no === selected ? "page" : undefined}
            onClick={() => showVersion(summary.version_no)}
            className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm ${
              summary.version_no === selected
                ? "border-primary bg-primary-soft text-primary"
                : "border-border bg-surface hover:bg-surface-muted"
            }`}
          >
            <span className="font-medium">v{summary.version_no}</span>
            <StatusBadge tone={RAB_STATUS[summary.status].tone}>{RAB_STATUS[summary.status].label}</StatusBadge>
          </button>
        ))}
      </nav>

      {version.isPending && <p className="text-sm text-muted">Memuat versi…</p>}
      {version.isError && <p className="text-sm text-danger">{errorMessage(version.error)}</p>}

      {v && (
        <>
          <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-2 text-sm">
              {!v.editable && <Lock aria-hidden className="mt-0.5 size-4 shrink-0 text-muted" />}
              <p>
                <span className="font-medium">Versi {v.version_no}</span>{" "}
                <StatusBadge tone={RAB_STATUS[v.status].tone}>{RAB_STATUS[v.status].label}</StatusBadge>
                <span className="block text-xs text-muted sm:inline sm:pl-2">
                  {lockedReason(v)}
                  {v.submitted_at && ` Diajukan ${formatTanggalWaktu(v.submitted_at)}${v.submitted_by ? ` oleh ${v.submitted_by.full_name}` : ""}.`}
                </span>
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {v.allowed_actions.map((a) => (
                <Button
                  key={a}
                  size="sm"
                  variant={a === "approve" || a === "submit" ? "primary" : RAB_ACTION[a].danger ? "danger" : "secondary"}
                  onClick={() => setAction(a)}
                >
                  {RAB_ACTION[a].label}
                </Button>
              ))}
              {v.can_create_version && (
                <Button size="sm" variant="secondary" loading={newVersion.isPending} onClick={() => newVersion.mutate()}>
                  <Plus aria-hidden className="size-4" />
                  Versi baru dari v{v.version_no}
                </Button>
              )}
            </div>
          </div>

          <div className="grid gap-5 xl:grid-cols-3">
            <div className="min-w-0 xl:col-span-2">
              <ItemsTable
                version={v}
                onAdd={() => setItemDialog({ open: true, item: null })}
                onEdit={(item) => setItemDialog({ open: true, item })}
                onDelete={setDeleting}
              />
            </div>
            <aside className="space-y-5">
              <TotalsCard version={v} onEdit={() => setAdjusting(true)} />
              <RabDocumentsCard rabId={id} rabNumber={doc.number} version={v} />
              <AiAssistantCard
                rabId={id}
                projectId={doc.project.id}
                version={v}
                onApplied={() => {
                  void version.refetch();
                  void queryClient.invalidateQueries({ queryKey: rabKeys.detail(id), exact: true });
                  void queryClient.invalidateQueries({ queryKey: ["rab", "list"] });
                }}
              />
              <IssuesCard issues={v.issues} />
              <NotesCard version={v} />
              <ApprovalHistory version={v} />
            </aside>
          </div>

          <ItemFormDialog
            open={itemDialog.open}
            item={itemDialog.item}
            currency={v.currency}
            onClose={() => setItemDialog({ open: false, item: null })}
            onSubmit={async (payload) => {
              const editing = itemDialog.item;
              try {
                const saved = editing
                  ? await api.put<RabVersion>(`${base}/items/${editing.id}`, {
                      ...payload,
                      row_version: editing.row_version,
                    })
                  : await api.post<RabVersion>(`${base}/items`, payload);
                applyVersion(saved);
                toast.success(editing ? "Item disimpan." : "Item ditambahkan.");
              } catch (error) {
                if (error instanceof ApiError && error.status === 409) void version.refetch();
                throw error;
              }
            }}
          />
          <AdjustmentsDialog
            open={adjusting}
            version={v}
            onClose={() => setAdjusting(false)}
            onSubmit={async (payload) => {
              try {
                applyVersion(await api.patch<RabVersion>(base, payload));
                toast.success("Pajak, diskon, dan catatan disimpan.");
              } catch (error) {
                if (error instanceof ApiError && error.status === 409) void version.refetch();
                throw error;
              }
            }}
          />
          <TransitionDialog
            action={action}
            versionNo={v.version_no}
            onClose={() => setAction(null)}
            onConfirm={async (chosen, note) => {
              const saved = await api.post<RabVersion>(`${base}/transitions/${chosen}`, { note });
              applyVersion(saved);
              toast.success(`Versi ${saved.version_no}: ${RAB_STATUS[saved.status].label}.`);
            }}
          />
          <ConfirmDialog
            open={deleting !== null}
            title="Hapus item?"
            message={
              <>
                Item <strong>{deleting?.name}</strong>
                {deleting?.subtotal ? ` (${formatMoney(deleting.subtotal, v.currency)})` : ""} akan dihapus
                dari versi {v.version_no}.
              </>
            }
            confirmLabel="Hapus"
            danger
            loading={removeItem.isPending}
            onConfirm={() => deleting && removeItem.mutate(deleting)}
            onClose={() => setDeleting(null)}
          />
        </>
      )}
    </div>
  );
}

function compareHref(id: string, selected: number): string {
  // Default: the selected version against its predecessor (v1 against v2).
  const [from, to] = selected > 1 ? [selected - 1, selected] : [1, 2];
  return `/rab/${id}/bandingkan?from=${from}&to=${to}`;
}

function lockedReason(version: RabVersion): string {
  switch (version.status) {
    case "draft":
      return version.editable ? "Dapat diedit." : "Anda hanya dapat melihat.";
    case "in_review":
      return "Terkunci selama review.";
    case "approved":
      return "Disetujui dan terkunci; perubahan dibuat sebagai versi baru.";
    case "rejected":
      return "Ditolak; buka kembali untuk merevisi.";
    case "archived":
      return "Diarsipkan (hanya baca).";
  }
}

function BackLink() {
  return (
    <Link href="/rab" className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground">
      <ArrowLeft aria-hidden className="size-4" />
      Kembali ke daftar RAB
    </Link>
  );
}
