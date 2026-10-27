// Display-only formatting. All monetary arithmetic happens in the backend; values arrive
// as decimal strings and are formatted without converting through floating point.

export const APP_TIME_ZONE = "Asia/Jakarta";
export const APP_LOCALE = "id-ID";

/** Shown wherever a value is missing or unreadable. */
export const EMPTY = "-";

const rupiahWhole = new Intl.NumberFormat(APP_LOCALE, {
  style: "currency",
  currency: "IDR",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

const rupiahCents = new Intl.NumberFormat(APP_LOCALE, {
  style: "currency",
  currency: "IDR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const DECIMAL_PATTERN = /^-?\d+(\.\d+)?$/;
const HAS_CENTS = /\.\d*[1-9]/;

/**
 * Formats a decimal string as Rupiah: whole amounts without decimals ("Rp 1.250.000"),
 * amounts with cents always with two ("Rp 1.250.000,50"). Invalid input yields EMPTY.
 */
export function formatRupiah(value: string | null | undefined): string {
  if (value == null) return EMPTY;
  const trimmed = value.trim();
  if (!DECIMAL_PATTERN.test(trimmed)) return EMPTY;
  // Intl.NumberFormat accepts numeric strings and keeps their full precision.
  const formatter = HAS_CENTS.test(trimmed) ? rupiahCents : rupiahWhole;
  return formatter.format(trimmed as Intl.StringNumericLiteral);
}

const percentFormatter = new Intl.NumberFormat(APP_LOCALE, { maximumFractionDigits: 2 });

/** "11.00" → "11%", "11.50" → "11,5%". */
export function formatPercent(value: string | null | undefined): string {
  if (value == null) return EMPTY;
  const trimmed = value.trim();
  if (!DECIMAL_PATTERN.test(trimmed)) return EMPTY;
  return `${percentFormatter.format(trimmed as Intl.StringNumericLiteral)}%`;
}

const dateFormatter = new Intl.DateTimeFormat(APP_LOCALE, {
  timeZone: APP_TIME_ZONE,
  day: "numeric",
  month: "long",
  year: "numeric",
});

const dateTimeFormatter = new Intl.DateTimeFormat(APP_LOCALE, {
  timeZone: APP_TIME_ZONE,
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZoneName: "short",
});

function toDate(value: string | Date): Date | null {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** "18 Oktober 2026" in Asia/Jakarta. */
export function formatTanggal(value: string | Date | null | undefined): string {
  if (value == null) return EMPTY;
  const date = toDate(value);
  return date ? dateFormatter.format(date) : EMPTY;
}

/** "18 Okt 2026, 20.30 WIB" in Asia/Jakarta. */
export function formatTanggalWaktu(value: string | Date | null | undefined): string {
  if (value == null) return EMPTY;
  const date = toDate(value);
  return date ? dateTimeFormatter.format(date) : EMPTY;
}

const isoDateFormatter = new Intl.DateTimeFormat("en-CA", { timeZone: APP_TIME_ZONE });

/** Today's calendar date in Asia/Jakarta as "YYYY-MM-DD" (for date inputs and comparisons). */
export function todayIso(now: Date = new Date()): string {
  return isoDateFormatter.format(now);
}

/** Decimal string in any ISO currency; Rupiah keeps its dedicated format. */
export function formatMoney(value: string | null | undefined, currency: string): string {
  if (currency === "IDR") return formatRupiah(value);
  if (value == null || !DECIMAL_PATTERN.test(value.trim())) return EMPTY;
  try {
    return new Intl.NumberFormat(APP_LOCALE, {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(value.trim() as Intl.StringNumericLiteral);
  } catch {
    return `${currency} ${value}`;
  }
}

const quantityFormatter = new Intl.NumberFormat(APP_LOCALE, { maximumFractionDigits: 4 });

/** "3.0000" → "3", "2.5000" → "2,5" (display only; the API keeps 4 decimals). */
export function formatQuantity(value: string | null | undefined): string {
  if (value == null) return EMPTY;
  const trimmed = value.trim();
  if (!DECIMAL_PATTERN.test(trimmed)) return EMPTY;
  return quantityFormatter.format(trimmed as Intl.StringNumericLiteral);
}

const unitPriceCache = new Map<string, Intl.NumberFormat>();

/**
 * Unit prices carry up to 4 decimals. Whole amounts show none; otherwise at least two and
 * at most four, so "33.3350" reads "Rp 33,335" instead of being rounded away.
 */
export function formatUnitPrice(value: string | null | undefined, currency = "IDR"): string {
  if (value == null) return EMPTY;
  const trimmed = value.trim();
  if (!DECIMAL_PATTERN.test(trimmed)) return EMPTY;
  const whole = !HAS_CENTS.test(trimmed);
  const key = `${currency}:${whole}`;
  let formatter = unitPriceCache.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat(APP_LOCALE, {
      style: "currency",
      currency,
      minimumFractionDigits: whole ? 0 : 2,
      maximumFractionDigits: whole ? 0 : 4,
    });
    unitPriceCache.set(key, formatter);
  }
  return formatter.format(trimmed as Intl.StringNumericLiteral);
}
