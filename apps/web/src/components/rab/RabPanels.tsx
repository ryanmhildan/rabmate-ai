"use client";

import { AlertCircle, AlertTriangle, Info, Pencil, Plus, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Table, TableMessage, Td, Th } from "@/components/ui/Table";
import {
  formatMoney,
  formatPercent,
  formatQuantity,
  formatTanggalWaktu,
  formatUnitPrice,
} from "@/lib/format";
import { APPROVAL_ACTION, PRICE_SOURCE_TYPE, RAB_ITEM_TYPE, VERIFICATION_STATUS } from "@/lib/labels";
import type { RabIssue, RabItem, RabVersion } from "@/lib/types";

// --------------------------------------------------------------------------- items

type ItemsTableProps = {
  version: RabVersion;
  onAdd?: () => void;
  onEdit?: (item: RabItem) => void;
  onDelete?: (item: RabItem) => void;
};

const COLUMNS = 8;

export function ItemsTable({ version, onAdd, onEdit, onDelete }: ItemsTableProps) {
  const errorItems = new Set(
    version.issues.filter((i) => i.severity === "error" && i.item_id).map((i) => i.item_id),
  );
  const editable = version.editable;

  return (
    <Card
      title={`Item (${version.items.length})`}
      actions={
        editable && onAdd ? (
          <Button size="sm" onClick={onAdd}>
            <Plus aria-hidden className="size-4" />
            Tambah item
          </Button>
        ) : undefined
      }
    >
      <Table label="Item RAB">
        <thead>
          <tr>
            <Th className="w-10">No</Th>
            <Th>Item</Th>
            <Th>Jenis</Th>
            <Th className="text-right">Kuantitas</Th>
            <Th className="text-right">Harga satuan</Th>
            <Th className="text-right">Subtotal</Th>
            <Th>Sumber harga</Th>
            <Th>
              <span className="sr-only">Aksi</span>
            </Th>
          </tr>
        </thead>
        <tbody>
          {version.items.length === 0 && (
            <TableMessage columns={COLUMNS}>
              {editable ? "Belum ada item. Tambahkan item pertama." : "Versi ini tidak memiliki item."}
            </TableMessage>
          )}
          {version.items.map((item, index) => (
            <tr key={item.id} className={errorItems.has(item.id) ? "bg-danger-soft/40" : undefined}>
              <Td className="tabular text-muted">{index + 1}</Td>
              <Td>
                <div className="font-medium">{item.name}</div>
                <div className="text-xs text-muted">
                  {[item.code, item.category].filter(Boolean).join(" · ")}
                </div>
                {item.specification && (
                  <div className="mt-0.5 line-clamp-2 text-xs whitespace-pre-wrap text-muted">
                    {item.specification}
                  </div>
                )}
              </Td>
              <Td className="text-xs">{RAB_ITEM_TYPE[item.item_type]}</Td>
              <Td className="tabular text-right whitespace-nowrap">
                {formatQuantity(item.quantity)} {item.unit}
              </Td>
              <Td className="tabular text-right whitespace-nowrap">
                {item.unit_price === null ? (
                  <StatusBadge tone="danger">Belum ada harga</StatusBadge>
                ) : (
                  formatUnitPrice(item.unit_price, version.currency)
                )}
              </Td>
              <Td className="tabular text-right font-medium whitespace-nowrap">
                {item.subtotal === null ? "—" : formatMoney(item.subtotal, version.currency)}
              </Td>
              <Td className="max-w-48 text-xs">
                {item.price_source_type && (
                  <div className="text-muted">{PRICE_SOURCE_TYPE[item.price_source_type]}</div>
                )}
                <div className="break-words">{item.price_source ?? <span className="text-warning">Tidak dicantumkan</span>}</div>
                {item.price_verification_status && (
                  <div className="mt-1">
                    <StatusBadge tone={VERIFICATION_STATUS[item.price_verification_status].tone}>
                      {VERIFICATION_STATUS[item.price_verification_status].label}
                    </StatusBadge>
                  </div>
                )}
              </Td>
              <Td className="text-right">
                {editable && (
                  <div className="flex justify-end gap-1">
                    {onEdit && (
                      <Button variant="ghost" size="sm" aria-label={`Ubah ${item.name}`} onClick={() => onEdit(item)}>
                        <Pencil className="size-4" />
                      </Button>
                    )}
                    {onDelete && (
                      <Button variant="ghost" size="sm" aria-label={`Hapus ${item.name}`} onClick={() => onDelete(item)}>
                        <Trash2 className="size-4" />
                      </Button>
                    )}
                  </div>
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  );
}

// --------------------------------------------------------------------------- totals

export function TotalsCard({ version, onEdit }: { version: RabVersion; onEdit?: () => void }) {
  const { totals, currency } = version;
  const money = (value: string) => formatMoney(value, currency);
  const discountLabel =
    version.discount_type === "percent"
      ? `Diskon ${formatPercent(version.discount_value)}`
      : version.discount_type === "amount"
        ? "Diskon (nominal)"
        : "Diskon";

  return (
    <Card
      title="Ringkasan biaya"
      actions={
        version.editable && onEdit ? (
          <Button variant="secondary" size="sm" onClick={onEdit}>
            Pajak & diskon
          </Button>
        ) : undefined
      }
    >
      <dl className="space-y-2 text-sm">
        <Row label="Subtotal">{money(totals.subtotal)}</Row>
        <Row label={discountLabel}>
          {version.discount_type === "none" ? "—" : `− ${money(totals.discount_amount)}`}
        </Row>
        <Row label="Dasar pengenaan pajak (DPP)">{money(totals.taxable_base)}</Row>
        <Row
          label={
            version.tax_label
              ? `${version.tax_label} ${formatPercent(version.tax_rate_percent)}`
              : "Pajak (belum dikonfigurasi)"
          }
        >
          {version.tax_label ? money(totals.tax_amount) : "—"}
        </Row>
        <div className="flex items-baseline justify-between gap-4 border-t border-border pt-2">
          <dt className="font-semibold">Grand total</dt>
          <dd className="tabular text-lg font-semibold">{money(totals.grand_total)}</dd>
        </div>
      </dl>
      {totals.unpriced_items > 0 && (
        <p className="rounded-md bg-warning-soft px-3 py-2 text-xs text-warning">
          {totals.unpriced_items} item belum memiliki harga dan belum masuk ke total.
        </p>
      )}
    </Card>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-muted">{label}</dt>
      <dd className="tabular text-right">{children}</dd>
    </div>
  );
}

// --------------------------------------------------------------------------- issues

const SEVERITY = {
  error: { icon: AlertCircle, className: "text-danger", label: "Kesalahan" },
  warning: { icon: AlertTriangle, className: "text-warning", label: "Peringatan" },
  info: { icon: Info, className: "text-muted", label: "Info" },
} as const;

export function IssuesCard({ issues }: { issues: RabIssue[] }) {
  const errors = issues.filter((i) => i.severity === "error").length;
  return (
    <Card title="Validasi">
      {issues.length === 0 ? (
        <p className="text-sm text-success">Tidak ada masalah. RAB siap diajukan.</p>
      ) : (
        <>
          <p className="text-xs text-muted">
            {errors > 0
              ? `${errors} kesalahan harus diperbaiki sebelum diajukan.`
              : "Tidak ada kesalahan; peringatan tidak menghalangi pengajuan."}
          </p>
          <ul className="space-y-1.5">
            {issues.map((issue, index) => {
              const meta = SEVERITY[issue.severity];
              const Icon = meta.icon;
              return (
                <li key={`${issue.code}-${index}`} className="flex gap-2 text-sm">
                  <Icon aria-label={meta.label} className={`mt-0.5 size-4 shrink-0 ${meta.className}`} />
                  <span>{issue.message}</span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </Card>
  );
}

// --------------------------------------------------------------------------- approvals

export function ApprovalHistory({ version }: { version: RabVersion }) {
  return (
    <Card title="Riwayat persetujuan">
      {version.approvals.length === 0 ? (
        <p className="text-sm text-muted">Belum pernah diajukan.</p>
      ) : (
        <ol className="space-y-3">
          {version.approvals.map((entry, index) => (
            <li key={`${entry.created_at}-${index}`} className="text-sm">
              <p>
                <span className="font-medium">{entry.actor?.full_name ?? "Sistem"}</span>{" "}
                {APPROVAL_ACTION[entry.action]}
              </p>
              <time dateTime={entry.created_at} className="text-xs text-muted">
                {formatTanggalWaktu(entry.created_at)}
              </time>
              {entry.note && (
                <p className="mt-1 rounded-md bg-surface-muted px-2 py-1 text-xs whitespace-pre-wrap">
                  {entry.note}
                </p>
              )}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

export function NotesCard({ version }: { version: RabVersion }) {
  if (!version.notes && !version.assumptions) return null;
  return (
    <Card title="Catatan & asumsi">
      {version.notes && (
        <div className="text-sm">
          <p className="text-xs text-muted">Catatan</p>
          <p className="whitespace-pre-wrap">{version.notes}</p>
        </div>
      )}
      {version.assumptions && (
        <div className="text-sm">
          <p className="text-xs text-muted">Asumsi</p>
          <p className="whitespace-pre-wrap">{version.assumptions}</p>
        </div>
      )}
    </Card>
  );
}
