"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Card } from "@/components/ui/Card";
import { Select } from "@/components/ui/Field";
import { FullPageMessage } from "@/components/ui/FullPageMessage";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge, type BadgeTone } from "@/components/ui/StatusBadge";
import { Table, TableMessage, Td, Th } from "@/components/ui/Table";
import { api, errorMessage } from "@/lib/api";
import { formatMoney, formatQuantity, formatUnitPrice } from "@/lib/format";
import { FIELD_LABELS } from "@/lib/labels";
import type { CompareLine, Rab, RabComparison } from "@/lib/types";

const KIND: Record<CompareLine["kind"], { label: string; tone: BadgeTone }> = {
  added: { label: "Baru", tone: "success" },
  removed: { label: "Dihapus", tone: "danger" },
  changed: { label: "Berubah", tone: "warning" },
  unchanged: { label: "Sama", tone: "neutral" },
};

function signed(value: string, currency: string): string {
  if (value.startsWith("-")) return `− ${formatMoney(value.slice(1), currency)}`;
  if (/^0(\.0+)?$/.test(value)) return formatMoney(value, currency);
  return `+ ${formatMoney(value, currency)}`;
}

export function ComparePage() {
  const { id } = useParams<{ id: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const from = Number(search.get("from"));
  const to = Number(search.get("to"));

  const rab = useQuery({ queryKey: ["rab", id], queryFn: () => api.get<Rab>(`/rab/${id}`) });
  const valid = from > 0 && to > 0 && from !== to;
  const comparison = useQuery({
    queryKey: ["rab", id, "compare", from, to],
    queryFn: () => api.get<RabComparison>(`/rab/${id}/compare?from=${from}&to=${to}`),
    enabled: valid,
  });

  if (rab.isPending) return <FullPageMessage loading title="Memuat RAB…" />;
  if (rab.isError) return <PageHeader title="RAB gagal dimuat" description={errorMessage(rab.error)} />;

  const versions = rab.data.versions.map((v) => v.version_no);
  const choose = (next: { from?: number; to?: number }) =>
    router.replace(`/rab/${id}/bandingkan?from=${next.from ?? from}&to=${next.to ?? to}`);
  const data = comparison.data;
  const currency = data?.currency ?? "IDR";

  return (
    <div className="space-y-5">
      <Link
        href={`/rab/${id}?v=${to || ""}`}
        className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground"
      >
        <ArrowLeft aria-hidden className="size-4" />
        Kembali ke {rab.data.number}
      </Link>
      <PageHeader title={`Bandingkan versi: ${rab.data.title}`} description={rab.data.number} />

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span>Dari</span>
        <Select aria-label="Versi awal" value={from || ""} onChange={(e) => choose({ from: Number(e.target.value) })} className="w-24">
          <option value="">-</option>
          {versions.map((n) => (
            <option key={n} value={n}>
              v{n}
            </option>
          ))}
        </Select>
        <span>ke</span>
        <Select aria-label="Versi pembanding" value={to || ""} onChange={(e) => choose({ to: Number(e.target.value) })} className="w-24">
          <option value="">-</option>
          {versions.map((n) => (
            <option key={n} value={n}>
              v{n}
            </option>
          ))}
        </Select>
      </div>

      {!valid && <p className="text-sm text-muted">Pilih dua versi yang berbeda.</p>}
      {comparison.isError && <p className="text-sm text-danger">{errorMessage(comparison.error)}</p>}

      {data && (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Card title={`Grand total v${data.from_version_no}`}>
              <p className="tabular text-lg font-semibold">{formatMoney(data.before_totals.grand_total, currency)}</p>
            </Card>
            <Card title={`Grand total v${data.to_version_no}`}>
              <p className="tabular text-lg font-semibold">{formatMoney(data.after_totals.grand_total, currency)}</p>
            </Card>
            <Card title="Selisih">
              <p className="tabular text-lg font-semibold">{signed(data.grand_total_delta, currency)}</p>
            </Card>
          </div>
          <Table label="Perbandingan item">
            <thead>
              <tr>
                <Th>Status</Th>
                <Th>Item</Th>
                <Th className="text-right">Kuantitas</Th>
                <Th className="text-right">Harga satuan</Th>
                <Th className="text-right">Subtotal</Th>
                <Th className="text-right">Selisih</Th>
              </tr>
            </thead>
            <tbody>
              {data.lines.length === 0 && <TableMessage columns={6}>Kedua versi tidak memiliki item.</TableMessage>}
              {data.lines.map((line, index) => (
                <tr key={`${line.kind}-${line.code ?? line.name}-${index}`}>
                  <Td>
                    <StatusBadge tone={KIND[line.kind].tone}>{KIND[line.kind].label}</StatusBadge>
                  </Td>
                  <Td>
                    <div className="font-medium">{line.name}</div>
                    {line.code && <div className="text-xs text-muted">{line.code}</div>}
                    {line.changed_fields.length > 0 && (
                      <div className="text-xs text-warning">
                        Berubah: {line.changed_fields.map((f) => FIELD_LABELS[f] ?? f).join(", ")}
                      </div>
                    )}
                  </Td>
                  <Td className="tabular text-right text-xs whitespace-nowrap">
                    <Diff
                      before={line.before_quantity && `${formatQuantity(line.before_quantity)} ${line.unit}`}
                      after={line.after_quantity && `${formatQuantity(line.after_quantity)} ${line.unit}`}
                    />
                  </Td>
                  <Td className="tabular text-right text-xs whitespace-nowrap">
                    <Diff
                      before={line.before_unit_price && formatUnitPrice(line.before_unit_price, currency)}
                      after={line.after_unit_price && formatUnitPrice(line.after_unit_price, currency)}
                    />
                  </Td>
                  <Td className="tabular text-right text-xs whitespace-nowrap">
                    <Diff
                      before={line.before_subtotal && formatMoney(line.before_subtotal, currency)}
                      after={line.after_subtotal && formatMoney(line.after_subtotal, currency)}
                    />
                  </Td>
                  <Td className="tabular text-right whitespace-nowrap">{signed(line.subtotal_delta, currency)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </>
      )}
    </div>
  );
}

function Diff({ before, after }: { before: string | null; after: string | null }) {
  if (before === after) return <span>{after ?? "-"}</span>;
  return (
    <span className="flex flex-col items-end">
      <span className="text-muted line-through">{before ?? "-"}</span>
      <span>{after ?? "-"}</span>
    </span>
  );
}
