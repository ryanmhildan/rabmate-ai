"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { api, errorMessage, queryString } from "@/lib/api";
import { formatTanggal, formatUnitPrice } from "@/lib/format";
import { MATCH_LEVEL } from "@/lib/labels";
import type { PriceCandidate } from "@/lib/types";

export type CandidateSearch = { name: string; unit: string; specification: string; currency: string };

/**
 * Lists price candidates from the catalog and approved RAB history. Candidates are suggestions:
 * nothing is applied until the user picks one, and a unit mismatch can never be applied.
 */
export function PriceCandidatesPanel({
  search,
  onUse,
}: {
  search: CandidateSearch;
  onUse: (candidate: PriceCandidate) => void;
}) {
  const candidates = useQuery({
    queryKey: ["price-catalog", "candidates", search],
    queryFn: ({ signal }) =>
      api.get<PriceCandidate[]>(
        `/price-catalog/candidates${queryString({
          name: search.name,
          unit: search.unit,
          specification: search.specification.slice(0, 2000),
          currency: search.currency,
          limit: 8,
        })}`,
        { signal },
      ),
    staleTime: 30_000,
  });

  return (
    <section aria-label="Kandidat harga" className="space-y-2 rounded-md border border-border bg-surface-muted/40 p-3">
      <p className="text-xs text-muted">
        Kandidat dari katalog dan RAB yang sudah disetujui, diurutkan menurut kecocokan. Periksa
        spesifikasi sebelum memakai.
      </p>
      {candidates.isPending && <p className="text-sm text-muted">Mencari kandidat…</p>}
      {candidates.isError && <p className="text-sm text-danger">{errorMessage(candidates.error)}</p>}
      {candidates.isSuccess && candidates.data.length === 0 && (
        <p className="text-sm text-muted">
          Tidak ada kandidat yang cocok. Isi harga manual beserta sumbernya, atau tambahkan item ke
          katalog harga.
        </p>
      )}
      <ul className="space-y-2">
        {candidates.data?.map((c) => (
          <CandidateCard key={`${c.kind}-${c.observation_id ?? c.reference ?? c.name}`} candidate={c} onUse={onUse} />
        ))}
      </ul>
    </section>
  );
}

function CandidateCard({ candidate: c, onUse }: { candidate: PriceCandidate; onUse: (c: PriceCandidate) => void }) {
  const level = MATCH_LEVEL[c.level];
  return (
    <li className="rounded-md border border-border bg-surface p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-medium break-words">{c.name}</div>
          <div className="text-xs text-muted">
            {[c.kind === "catalog" ? "Katalog" : "Riwayat RAB", c.brand, c.specification].filter(Boolean).join(" · ")}
          </div>
        </div>
        <div className="text-right">
          <div className="tabular font-medium whitespace-nowrap">
            {formatUnitPrice(c.price, c.currency)} <span className="text-xs font-normal text-muted">/ {c.unit}</span>
          </div>
          <div className="text-xs text-muted">{c.observed_at ? formatTanggal(c.observed_at) : ""}</div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <StatusBadge tone={level.tone}>{`${level.label} (${c.score})`}</StatusBadge>
        {c.kind === "catalog" && (
          <StatusBadge tone={c.verified ? "success" : "warning"}>
            {c.verified ? "Terverifikasi" : "Belum terverifikasi"}
          </StatusBadge>
        )}
        {(c.supplier || c.source_reference || c.reference) && (
          <span className="text-xs text-muted break-words">
            {[c.supplier, c.source_reference, c.reference].filter(Boolean).join(" · ")}
          </span>
        )}
      </div>
      {c.reasons.length > 0 && <p className="mt-1 text-xs text-muted">{c.reasons.join(" ")}</p>}
      {c.warnings.length > 0 && (
        <ul className="mt-1 space-y-0.5 text-xs text-warning">
          {c.warnings.map((w) => (
            <li key={w} className="flex gap-1">
              <AlertTriangle aria-hidden className="mt-0.5 size-3 shrink-0" />
              {w}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-2 flex justify-end">
        <Button
          size="sm"
          variant="secondary"
          disabled={!c.unit_compatible}
          title={c.unit_compatible ? undefined : "Satuan berbeda; tidak dapat dipakai langsung."}
          aria-label={`Gunakan harga ${c.name}`}
          onClick={() => onUse(c)}
        >
          {c.unit_compatible ? "Gunakan" : "Satuan berbeda"}
        </Button>
      </div>
    </li>
  );
}
