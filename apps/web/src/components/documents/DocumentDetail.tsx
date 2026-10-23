"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Ban, Download } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";
import { AuditList } from "@/components/audit/AuditList";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { FullPageMessage } from "@/components/ui/FullPageMessage";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { documentFileUrl, formatBytes } from "@/lib/documents";
import { formatMoney, formatPercent, formatTanggalWaktu } from "@/lib/format";
import { DOCUMENT_STATUS, DOCUMENT_TYPE } from "@/lib/labels";
import type { IssuedDocument, IssuedDocumentDetail, RabSnapshot } from "@/lib/types";
import { VoidDocumentDialog } from "./VoidDocumentDialog";

export function DocumentDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const canIssue = useCan("documents.issue");
  const canAudit = useCan("audit.read");
  const [voiding, setVoiding] = useState(false);
  const queryKey = ["documents", "detail", id];

  const detail = useQuery({
    queryKey,
    queryFn: ({ signal }) => api.get<IssuedDocumentDetail>(`/documents/${id}`, { signal }),
    retry: false,
  });

  if (detail.isPending) return <FullPageMessage loading title="Memuat dokumen…" />;
  if (detail.isError) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <div className="space-y-4">
        <BackLink />
        <PageHeader
          title={notFound ? "Dokumen tidak ditemukan" : "Dokumen gagal dimuat"}
          description={notFound ? "Dokumen mungkin milik organisasi lain." : errorMessage(detail.error)}
        />
      </div>
    );
  }

  const d = detail.data;
  const status = DOCUMENT_STATUS[d.status];
  const source = sourceLink(d);
  // RAB documents are voided here; the others from their source page, which also voids the record.
  const voidHere = d.doc_type === "rab";

  return (
    <div className="space-y-6">
      <BackLink />
      <PageHeader
        title={d.number}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
            <span>{DOCUMENT_TYPE[d.doc_type]}</span>
            <span>· {d.title}</span>
          </span>
        }
        actions={
          canIssue &&
          voidHere &&
          d.status === "issued" && (
            <Button variant="secondary" onClick={() => setVoiding(true)}>
              <Ban aria-hidden className="size-4" />
              Batalkan
            </Button>
          )
        }
      />

      {d.status === "void" && (
        <div role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
          Dibatalkan {formatTanggalWaktu(d.voided_at)}
          {d.voided_by && ` oleh ${d.voided_by.full_name}`}. Alasan: {d.void_reason}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          {d.doc_type === "rab" ? (
            <RabSnapshotCard s={d.snapshot as RabSnapshot} />
          ) : (
            <Card title="Isi dokumen (snapshot)">
              <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
                <Info label="Proyek">
                  {d.snapshot.project.number} — {d.snapshot.project.name}
                </Info>
                <Info label="Klien">{d.snapshot.client?.name ?? "—"}</Info>
                <Info label="Perusahaan">{d.snapshot.company.legal_name ?? d.snapshot.company.name}</Info>
                {d.doc_type !== "bast" && <Info label="Nilai">{formatMoney(d.total_amount, d.currency)}</Info>}
                {source && (
                  <Info label="Sumber">
                    <Link href={source.href} className="text-primary hover:underline">
                      {source.label}
                    </Link>
                  </Info>
                )}
              </dl>
              <p className="text-xs text-muted">
                Isi lengkap ada pada berkas PDF tersimpan. Pembatalan dilakukan dari halaman sumbernya.
              </p>
            </Card>
          )}
          {canAudit && (
            <Card title="Aktivitas">
              <AuditList entityType="document" entityId={d.id} />
            </Card>
          )}
        </div>
        <aside className="space-y-5">
          <Card title="Berkas tersimpan">
            <ul className="space-y-3">
              {d.files.map((f) => (
                <li key={f.format} className="space-y-1 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{f.filename}</span>
                    <a
                      href={documentFileUrl(d.id, f.format, f.format === "xlsx")}
                      target={f.format === "pdf" ? "_blank" : undefined}
                      rel="noopener"
                      className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs font-medium hover:bg-surface-muted"
                    >
                      <Download aria-hidden className="size-3.5" />
                      Unduh
                    </a>
                  </div>
                  <p className="text-xs text-muted">{formatBytes(f.size_bytes)}</p>
                  <p className="font-mono text-[11px] break-all text-muted" title="SHA-256 berkas">
                    {f.sha256}
                  </p>
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Integritas">
            <dl className="space-y-2 text-sm">
              <Info label="Diterbitkan">
                {formatTanggalWaktu(d.issued_at)}
                {d.issued_by && ` oleh ${d.issued_by.full_name}`}
              </Info>
              <Info label="Kode verifikasi (SHA-256 snapshot)">
                <span className="font-mono text-[11px] break-all">{d.snapshot_sha256}</span>
              </Info>
              <Info label="Versi skema">{d.schema_version}</Info>
            </dl>
            <p className="text-xs text-muted">
              16 karakter pertama kode verifikasi tercetak di kaki setiap halaman PDF.
            </p>
          </Card>
        </aside>
      </div>

      <VoidDocumentDialog
        number={voiding ? d.number : null}
        onClose={() => setVoiding(false)}
        onConfirm={async (reason) => {
          const saved = await api.post<IssuedDocument>(`/documents/${id}/void`, { reason });
          void queryClient.invalidateQueries({ queryKey: ["documents"] });
          void queryClient.invalidateQueries({ queryKey: ["audit"] });
          toast.success(`Dokumen ${saved.number} dibatalkan.`);
        }}
      />
    </div>
  );
}

function sourceLink(d: IssuedDocument): { href: string; label: string } | null {
  if (d.quotation_id) return { href: `/penawaran/${d.quotation_id}`, label: "Buka penawaran" };
  if (d.invoice_id) return { href: `/invoice/${d.invoice_id}`, label: "Buka invoice" };
  if (d.spk_id) return { href: `/spk-bast/spk/${d.spk_id}`, label: "Buka SPK" };
  if (d.bast_id) return { href: `/spk-bast/bast/${d.bast_id}`, label: "Buka BAST" };
  return null;
}

function RabSnapshotCard({ s }: { s: RabSnapshot }) {
  return (
    <Card title="Isi dokumen (snapshot)">
      <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
        <Info label="Proyek">
          {s.project.number} — {s.project.name}
        </Info>
        <Info label="Klien">{s.client?.name ?? "—"}</Info>
        <Info label="RAB">
          <Link href={`/rab/${s.rab.id}?v=${s.rab.version_no}`} className="text-primary hover:underline">
            {s.rab.number} versi {s.rab.version_no}
          </Link>{" "}
          ({s.rab.status_label} saat terbit)
        </Info>
        <Info label="Disetujui">
          {s.rab.approved_by ?? "—"}
          {s.rab.approved_at && `, ${formatTanggalWaktu(s.rab.approved_at)}`}
        </Info>
        <Info label="Perusahaan">{s.company.legal_name ?? s.company.name}</Info>
        <Info label="Jumlah item">{s.items.length}</Info>
      </dl>
      <dl className="space-y-1 border-t border-border pt-3 text-sm">
        <Row label="Subtotal" value={formatMoney(s.totals.subtotal, s.rab.currency)} />
        {s.totals.discount_amount !== "0.00" && (
          <Row label="Diskon" value={`− ${formatMoney(s.totals.discount_amount, s.rab.currency)}`} />
        )}
        {s.totals.tax_label && (
          <Row
            label={`${s.totals.tax_label} ${formatPercent(s.totals.tax_rate_percent)}`}
            value={formatMoney(s.totals.tax_amount, s.rab.currency)}
          />
        )}
        <Row label="Total" value={formatMoney(s.totals.grand_total, s.rab.currency)} strong />
      </dl>
      {s.totals.amount_in_words && <p className="text-xs text-muted italic">Terbilang: {s.totals.amount_in_words}</p>}
    </Card>
  );
}

function BackLink() {
  return (
    <Link href="/dokumen" className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground">
      <ArrowLeft aria-hidden className="size-4" />
      Kembali ke daftar dokumen
    </Link>
  );
}

function Info({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  );
}

function Row({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={`flex justify-between gap-4 ${strong ? "font-semibold" : ""}`}>
      <dt>{label}</dt>
      <dd className="tabular">{value}</dd>
    </div>
  );
}
