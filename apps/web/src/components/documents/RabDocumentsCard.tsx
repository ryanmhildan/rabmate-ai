"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Eye, FileSignature, FileSpreadsheet, FileUp, Stamp } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { api, errorMessage, queryString } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { documentFileUrl, exportXlsxUrl, previewPdfUrl } from "@/lib/documents";
import { formatMoney, formatTanggalWaktu } from "@/lib/format";
import { DOCUMENT_STATUS } from "@/lib/labels";
import type { IssuedDocument, Page, RabVersion } from "@/lib/types";
import { IssueDocumentDialog } from "./IssueDocumentDialog";

const LINK =
  "inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 text-xs font-medium hover:bg-surface-muted";

export function RabDocumentsCard({
  rabId,
  rabNumber,
  version,
}: {
  rabId: string;
  rabNumber: string;
  version: RabVersion;
}) {
  const canWrite = useCan("rab.write");
  const canIssue = useCan("documents.issue");
  const canReadDocuments = useCan("documents.read");
  const queryClient = useQueryClient();
  const [issuing, setIssuing] = useState(false);
  const [quoting, setQuoting] = useState(false);
  const router = useRouter();
  const queryKey = ["documents", "list", { rab_version_id: version.id }];

  const documents = useQuery({
    queryKey,
    queryFn: ({ signal }) =>
      api.get<Page<IssuedDocument>>(
        `/documents${queryString({ rab_version_id: version.id, page_size: 20 })}`,
        { signal },
      ),
    enabled: canReadDocuments,
  });
  const items = documents.data?.items ?? [];
  const active = items.find((d) => d.status === "issued");
  const approved = version.status === "approved";

  return (
    <Card title="Dokumen & ekspor">
      <div className="flex flex-wrap gap-2">
        <a href={previewPdfUrl(rabId, version.version_no)} target="_blank" rel="noopener" className={LINK}>
          <Eye aria-hidden className="size-3.5" />
          Pratinjau PDF
        </a>
        <a href={exportXlsxUrl(rabId, version.version_no)} download className={LINK}>
          <FileSpreadsheet aria-hidden className="size-3.5" />
          Ekspor XLSX
        </a>
        {canWrite && version.editable && (
          <Link href={`/rab/${rabId}/impor?versi=${version.version_no}`} className={LINK}>
            <FileUp aria-hidden className="size-3.5" />
            Impor item
          </Link>
        )}
      </div>
      <p className="text-xs text-muted">
        Pratinjau dan ekspor memakai data terkini dan bertanda pratinjau bila belum diterbitkan.
      </p>

      {approved && !active && documents.isSuccess && (
        canIssue ? (
          <Button size="sm" onClick={() => setIssuing(true)}>
            <Stamp aria-hidden className="size-4" />
            Terbitkan dokumen
          </Button>
        ) : (
          <p className="text-xs text-muted">
            Versi ini sudah disetujui dan siap diterbitkan oleh pengguna dengan izin penerbitan.
          </p>
        )
      )}
      {approved && canWrite && (
        <Button
          size="sm"
          variant="secondary"
          loading={quoting}
          onClick={async () => {
            setQuoting(true);
            try {
              const quotation = await api.post<{ id: string; number: string }>("/quotations", {
                rab_version_id: version.id,
              });
              void queryClient.invalidateQueries({ queryKey: ["quotations"] });
              toast.success(`Penawaran ${quotation.number} dibuat.`);
              router.push(`/penawaran/${quotation.id}`);
            } catch (error) {
              toast.error(errorMessage(error));
            } finally {
              setQuoting(false);
            }
          }}
        >
          <FileSignature aria-hidden className="size-4" />
          Buat penawaran
        </Button>
      )}
      {!approved && !active && (
        <p className="text-xs text-muted">Dokumen resmi dapat diterbitkan setelah versi disetujui.</p>
      )}

      {documents.isError && <p className="text-xs text-danger">{errorMessage(documents.error)}</p>}
      {items.length > 0 && (
        <ul className="divide-y divide-border rounded-md border border-border">
          {items.map((d) => (
            <li key={d.id} className="space-y-1 p-2.5 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Link href={`/dokumen/${d.id}`} className="font-mono text-xs font-medium text-primary hover:underline">
                  {d.number}
                </Link>
                <StatusBadge tone={DOCUMENT_STATUS[d.status].tone}>{DOCUMENT_STATUS[d.status].label}</StatusBadge>
              </div>
              <p className="text-xs text-muted">
                {formatTanggalWaktu(d.issued_at)}
                {d.issued_by && ` · ${d.issued_by.full_name}`}
              </p>
              <div className="flex gap-2">
                <a href={documentFileUrl(d.id, "pdf")} target="_blank" rel="noopener" className={LINK}>
                  <Download aria-hidden className="size-3.5" />
                  PDF
                </a>
                <a href={documentFileUrl(d.id, "xlsx", true)} className={LINK}>
                  <Download aria-hidden className="size-3.5" />
                  XLSX
                </a>
              </div>
            </li>
          ))}
        </ul>
      )}

      <IssueDocumentDialog
        open={issuing}
        endpoint={`/rab/${rabId}/versions/${version.version_no}/documents`}
        title="Terbitkan dokumen RAB"
        summary={
          <p>
            Versi {version.version_no} dari <strong>{rabNumber}</strong> senilai{" "}
            <strong className="tabular">{formatMoney(version.grand_total, version.currency)}</strong>{" "}
            diterbitkan dengan nomor dari server (mis. {rabNumber}/V{version.version_no}).
          </p>
        }
        onClose={() => setIssuing(false)}
        onIssued={(document) => {
          void queryClient.invalidateQueries({ queryKey: ["documents"] });
          void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
          toast.success(`Dokumen ${document.number} diterbitkan.`);
        }}
      />
    </Card>
  );
}
