import { ExternalLink } from "lucide-react";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { formatTanggal, formatUnitPrice } from "@/lib/format";
import { VERIFICATION_STATUS } from "@/lib/labels";
import type { PriceObservation } from "@/lib/types";

export function PriceWithStatus({ observation }: { observation: PriceObservation | null }) {
  if (!observation) return <span className="text-muted">-</span>;
  const status = VERIFICATION_STATUS[observation.verification_status];
  return (
    <div className="space-y-0.5">
      <div className="tabular font-medium whitespace-nowrap">
        {formatUnitPrice(observation.price, observation.currency)}
        <span className="text-xs font-normal text-muted"> / {observation.unit}</span>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
        <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
        <span>{formatTanggal(observation.observed_at)}</span>
      </div>
    </div>
  );
}

/** Only http(s) links are rendered (the API rejects other schemes too); opened without referrer. */
export function SourceLink({ url }: { url: string | null }) {
  if (!url || !/^https?:\/\//i.test(url)) return null;
  let host = url;
  try {
    host = new URL(url).host;
  } catch {
    return null;
  }
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="inline-flex items-center gap-1 text-primary hover:underline"
    >
      {host}
      <ExternalLink aria-hidden className="size-3" />
    </a>
  );
}
