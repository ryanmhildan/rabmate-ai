"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BadgeCheck, Pencil, Plus, XCircle } from "lucide-react";
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
import { Table, TableMessage, Td, Th } from "@/components/ui/Table";
import { ApiError, api, errorMessage } from "@/lib/api";
import { useCan } from "@/lib/auth";
import { formatTanggal, formatTanggalWaktu, formatUnitPrice, todayIso } from "@/lib/format";
import { OBSERVATION_SOURCE, RAB_ITEM_TYPE, VERIFICATION_STATUS } from "@/lib/labels";
import type { CatalogItemDetail as Detail, PriceObservation } from "@/lib/types";
import { CatalogItemFormDialog } from "./CatalogItemFormDialog";
import { ObservationFormDialog } from "./ObservationFormDialog";
import { PriceWithStatus, SourceLink } from "./PriceBits";
import { VerificationDialog } from "./VerificationDialog";

const COLUMNS = 6;

export function CatalogItemDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const canWrite = useCan("pricing.write");
  const canVerify = useCan("pricing.verify");
  const canAudit = useCan("audit.read");
  const [editing, setEditing] = useState(false);
  const [recording, setRecording] = useState(false);
  const [verifying, setVerifying] = useState<{
    observation: PriceObservation;
    status: "verified" | "rejected";
  } | null>(null);
  const queryKey = ["price-catalog", "detail", id];

  const detail = useQuery({
    queryKey,
    queryFn: ({ signal }) => api.get<Detail>(`/price-catalog/${id}`, { signal }),
    retry: false,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["price-catalog"] });
    void queryClient.invalidateQueries({ queryKey: ["audit"] });
  };

  if (detail.isPending) return <FullPageMessage loading title="Memuat item katalog…" />;
  if (detail.isError) {
    const notFound = detail.error instanceof ApiError && detail.error.status === 404;
    return (
      <div className="space-y-4">
        <BackLink />
        <PageHeader
          title={notFound ? "Item tidak ditemukan" : "Item gagal dimuat"}
          description={notFound ? "Item mungkin berada di organisasi lain atau sudah tidak ada." : errorMessage(detail.error)}
        />
      </div>
    );
  }

  const item = detail.data;

  return (
    <div className="space-y-6">
      <BackLink />
      <PageHeader
        title={item.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            {item.code && <span className="font-mono text-xs">{item.code}</span>}
            <span>{RAB_ITEM_TYPE[item.item_type]}</span>
            <span>· per {item.unit}</span>
            {!item.is_active && <StatusBadge tone="neutral">Nonaktif</StatusBadge>}
          </span>
        }
        actions={
          canWrite && (
            <>
              <Button variant="secondary" onClick={() => setEditing(true)}>
                <Pencil aria-hidden className="size-4" />
                Ubah
              </Button>
              <Button onClick={() => setRecording(true)}>
                <Plus aria-hidden className="size-4" />
                Catat harga
              </Button>
            </>
          )
        }
      />

      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Harga terverifikasi terakhir">
          <PriceWithStatus observation={item.prices.latest_verified} />
          {!item.prices.latest_verified && (
            <p className="text-xs text-muted">Belum ada harga yang diverifikasi untuk item ini.</p>
          )}
        </Card>
        <Card title="Harga terbaru">
          <PriceWithStatus observation={item.prices.latest_any} />
        </Card>
        <Card title="Detail">
          <dl className="grid gap-2 text-sm">
            <Info label="Kategori">{item.category ?? "-"}</Info>
            <Info label="Merek">{item.brand ?? "-"}</Info>
            <Info label="Spesifikasi">
              <span className="whitespace-pre-wrap">{item.specification ?? "-"}</span>
            </Info>
            {item.notes && (
              <Info label="Catatan">
                <span className="whitespace-pre-wrap">{item.notes}</span>
              </Info>
            )}
          </dl>
        </Card>
      </div>

      <section className="space-y-2">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold">Riwayat harga</h2>
          <span className="text-xs text-muted">
            Riwayat tidak pernah ditimpa; harga baru ditambahkan sebagai entri baru.
          </span>
        </div>
        <Table label="Riwayat harga">
          <thead>
            <tr>
              <Th>Tanggal</Th>
              <Th className="text-right">Harga</Th>
              <Th>Sumber</Th>
              <Th>Berlaku / lokasi</Th>
              <Th>Status</Th>
              <Th className="text-right">
                <span className="sr-only">Aksi</span>
              </Th>
            </tr>
          </thead>
          <tbody>
            {item.observations.length === 0 && (
              <TableMessage columns={COLUMNS}>Belum ada harga tercatat.</TableMessage>
            )}
            {item.observations.map((o) => (
              <ObservationRow
                key={o.id}
                observation={o}
                canVerify={canVerify}
                onVerify={(status) => setVerifying({ observation: o, status })}
              />
            ))}
          </tbody>
        </Table>
      </section>

      {canAudit && (
        <Card title="Aktivitas">
          <AuditList entityType="catalog_item" entityId={item.id} />
        </Card>
      )}

      <CatalogItemFormDialog
        open={editing}
        item={item}
        unitLocked={item.prices.observation_count > 0}
        onClose={() => setEditing(false)}
        onSubmit={async (payload) => {
          try {
            const saved = await api.patch<Detail>(`/price-catalog/${id}`, { ...payload, version: item.version });
            queryClient.setQueryData(queryKey, saved);
            refresh();
            toast.success("Perubahan disimpan.");
          } catch (error) {
            if (error instanceof ApiError && error.code === "version_conflict") void detail.refetch();
            throw error;
          }
        }}
      />
      <ObservationFormDialog
        open={recording}
        unit={item.unit}
        onClose={() => setRecording(false)}
        onSubmit={async (payload) => {
          await api.post<PriceObservation>(`/price-catalog/${id}/observations`, payload);
          refresh();
          toast.success("Harga dicatat (belum terverifikasi).");
        }}
      />
      <VerificationDialog
        target={verifying}
        onClose={() => setVerifying(null)}
        onConfirm={async (status, note) => {
          if (!verifying) return;
          await api.post<PriceObservation>(`/price-observations/${verifying.observation.id}/verification`, {
            status,
            note,
          });
          refresh();
          toast.success(status === "verified" ? "Harga diverifikasi." : "Harga ditolak.");
        }}
      />
    </div>
  );
}

function ObservationRow({
  observation: o,
  canVerify,
  onVerify,
}: {
  observation: PriceObservation;
  canVerify: boolean;
  onVerify: (status: "verified" | "rejected") => void;
}) {
  const status = VERIFICATION_STATUS[o.verification_status];
  const expired = o.valid_until !== null && o.valid_until < todayIso();
  return (
    <tr className="align-top hover:bg-surface-muted/50">
      <Td className="whitespace-nowrap">
        {formatTanggal(o.observed_at)}
        <div className="text-xs text-muted">{OBSERVATION_SOURCE[o.source_type]}</div>
      </Td>
      <Td className="text-right tabular whitespace-nowrap">
        {formatUnitPrice(o.price, o.currency)}
        <div className="text-xs text-muted">/ {o.unit}</div>
      </Td>
      <Td className="max-w-xs">
        <div className="space-y-0.5 text-sm break-words">
          {o.supplier && <div>{o.supplier.name}</div>}
          {o.source_reference && <div className="text-xs text-muted">{o.source_reference}</div>}
          <SourceLink url={o.source_url} />
          {!o.supplier && !o.source_reference && !o.source_url && (
            <div className="text-xs text-danger">Tanpa sumber</div>
          )}
          {o.observed_specification && (
            <div className="text-xs text-muted">Spesifikasi sumber: {o.observed_specification}</div>
          )}
        </div>
      </Td>
      <Td className="text-xs text-muted">
        {o.valid_from || o.valid_until ? (
          <div className={expired ? "text-warning" : undefined}>
            {o.valid_from ? formatTanggal(o.valid_from) : "…"} – {o.valid_until ? formatTanggal(o.valid_until) : "…"}
            {expired && " (kedaluwarsa)"}
          </div>
        ) : (
          <div>-</div>
        )}
        {o.location && <div>{o.location}</div>}
      </Td>
      <Td>
        <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
        {o.verified_by && o.verified_at && (
          <div className="mt-1 text-xs text-muted">
            {o.verified_by.full_name} · {formatTanggalWaktu(o.verified_at)}
          </div>
        )}
        {o.verification_note && <div className="mt-0.5 text-xs text-muted">“{o.verification_note}”</div>}
      </Td>
      <Td className="text-right">
        {canVerify && o.verification_status !== "rejected" && (
          <div className="flex justify-end gap-1">
            {o.verification_status === "unverified" && (
              <Button variant="ghost" size="sm" aria-label="Verifikasi harga" onClick={() => onVerify("verified")}>
                <BadgeCheck className="size-4" />
              </Button>
            )}
            <Button variant="ghost" size="sm" aria-label="Tolak harga" onClick={() => onVerify("rejected")}>
              <XCircle className="size-4" />
            </Button>
          </div>
        )}
      </Td>
    </tr>
  );
}

function BackLink() {
  return (
    <Link href="/katalog-harga" className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground">
      <ArrowLeft aria-hidden className="size-4" />
      Kembali ke katalog harga
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
