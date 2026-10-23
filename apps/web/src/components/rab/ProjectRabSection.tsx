"use client";

import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { api, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { formatMoney } from "@/lib/format";
import { RAB_STATUS } from "@/lib/labels";
import type { Page, Project, RabListItem } from "@/lib/types";
import { NewRabDialog } from "./NewRabDialog";

const ACCEPTS_RAB = new Set(["prospect", "active", "on_hold"]);

export function ProjectRabSection({ project }: { project: Project }) {
  const canRead = useCan("rab.read");
  const canWrite = useCan("rab.write");
  const [creating, setCreating] = useState(false);
  const list = useQuery({
    queryKey: ["rab", "list", { project: project.id }],
    queryFn: () => api.get<Page<RabListItem>>(`/projects/${project.id}/rab?page_size=50`),
    enabled: canRead,
  });

  if (!canRead) return null;
  const accepts = ACCEPTS_RAB.has(project.status);

  return (
    <Card
      title="RAB"
      actions={
        canWrite && accepts ? (
          <Button size="sm" variant="secondary" onClick={() => setCreating(true)}>
            <Plus aria-hidden className="size-4" />
            Buat RAB
          </Button>
        ) : undefined
      }
    >
      {list.isPending && <p className="text-sm text-muted">Memuat RAB…</p>}
      {list.isError && <p className="text-sm text-danger">{errorMessage(list.error)}</p>}
      {list.data?.total === 0 && (
        <p className="text-sm text-muted">
          Belum ada RAB.{" "}
          {!accepts && "RAB baru hanya dapat dibuat untuk proyek prospek, berjalan, atau ditunda."}
        </p>
      )}
      <ul className="divide-y divide-border">
        {list.data?.items.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <div className="min-w-0">
              <Link href={`/rab/${r.id}`} className="font-medium text-primary hover:underline">
                {r.title}
              </Link>
              <div className="font-mono text-xs text-muted">
                {r.number} · v{r.latest_version_no}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <StatusBadge tone={RAB_STATUS[r.latest_status].tone}>{RAB_STATUS[r.latest_status].label}</StatusBadge>
              <span className="tabular">{formatMoney(r.grand_total, r.currency)}</span>
            </div>
          </li>
        ))}
      </ul>
      <NewRabDialog
        open={creating}
        onClose={() => setCreating(false)}
        project={{ id: project.id, label: `${project.number} — ${project.name}` }}
      />
    </Card>
  );
}
