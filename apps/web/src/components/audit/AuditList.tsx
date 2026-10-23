"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Pagination } from "@/components/ui/Pagination";
import { api, errorMessage, queryString } from "@/lib/api";
import { formatTanggalWaktu } from "@/lib/format";
import {
  DOCUMENT_STATUS,
  FIELD_LABELS,
  PROJECT_STATUS,
  VERIFICATION_STATUS,
  auditActionLabel,
} from "@/lib/labels";
import type { AuditEntry, DocumentStatus, Page, ProjectStatus, VerificationStatus } from "@/lib/types";

const ROLE_NAMES: Record<string, string> = {
  owner: "Owner/Admin",
  project_manager: "Project Manager",
  estimator: "Estimator",
  finance: "Finance",
  approver: "Approver",
  viewer: "Viewer",
};

function describeValue(field: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "kosong";
  if (field === "status" && typeof value === "string" && value in PROJECT_STATUS) {
    return PROJECT_STATUS[value as ProjectStatus].label;
  }
  if (field === "status" && typeof value === "string" && value in DOCUMENT_STATUS) {
    return DOCUMENT_STATUS[value as DocumentStatus].label;
  }
  if (field === "verification_status" && typeof value === "string" && value in VERIFICATION_STATUS) {
    return VERIFICATION_STATUS[value as VerificationStatus].label;
  }
  if (field === "role" && typeof value === "string") return ROLE_NAMES[value] ?? value;
  if (typeof value === "boolean") return value ? "ya" : "tidak";
  if (field === "members" && typeof value === "object") return `${Object.keys(value).length} orang`;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function ChangeList({ changes }: { changes: AuditEntry["changes"] }) {
  if (!changes) return null;
  return (
    <ul className="mt-1 space-y-0.5 text-xs text-muted">
      {Object.entries(changes).map(([field, change]) => (
        <li key={field} className="break-words">
          <span className="text-foreground/80">{FIELD_LABELS[field] ?? field}</span>
          {/* Reference ids mean nothing to people; the entity name lives on the record itself. */}
          {field.endsWith("_id") ? (
            <>: diubah</>
          ) : (
            <>
              : {describeValue(field, change.from)} →{" "}
              <span className="text-foreground">{describeValue(field, change.to)}</span>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

export function AuditItem({ entry, showSummary = true }: { entry: AuditEntry; showSummary?: boolean }) {
  return (
    <li className="border-b border-border py-2.5 last:border-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <p className="text-sm">
          <span className="font-medium">{entry.actor?.full_name ?? "Sistem"}</span>{" "}
          {auditActionLabel(entry.action).toLowerCase()}
          {showSummary && entry.summary && <span className="text-muted"> · {entry.summary}</span>}
        </p>
        <time dateTime={entry.created_at} className="text-xs text-muted">
          {formatTanggalWaktu(entry.created_at)}
        </time>
      </div>
      {!entry.action.endsWith(".create") && <ChangeList changes={entry.changes} />}
    </li>
  );
}

type Props = { entityType?: string; entityId?: string; pageSize?: number };

export function AuditList({ entityType, entityId, pageSize = 10 }: Props) {
  const [page, setPage] = useState(1);
  const list = useQuery({
    queryKey: ["audit", { entityType, entityId, page, pageSize }],
    queryFn: ({ signal }) =>
      api.get<Page<AuditEntry>>(
        `/audit-logs${queryString({ entity_type: entityType, entity_id: entityId, page, page_size: pageSize })}`,
        { signal },
      ),
    placeholderData: keepPreviousData,
  });

  if (list.isPending) return <p className="text-sm text-muted">Memuat aktivitas…</p>;
  if (list.isError) {
    return (
      <p className="text-sm text-danger">
        {errorMessage(list.error)}{" "}
        <Button variant="ghost" size="sm" onClick={() => void list.refetch()}>
          Coba lagi
        </Button>
      </p>
    );
  }
  if (list.data.total === 0) return <p className="text-sm text-muted">Belum ada aktivitas.</p>;

  return (
    <div className="space-y-3">
      <ul>
        {list.data.items.map((entry) => (
          <AuditItem key={entry.id} entry={entry} showSummary={!entityId} />
        ))}
      </ul>
      {list.data.total > pageSize && (
        <Pagination page={page} pageSize={pageSize} total={list.data.total} onPageChange={setPage} />
      )}
    </div>
  );
}
