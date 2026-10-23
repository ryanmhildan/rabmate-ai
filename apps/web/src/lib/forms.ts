import type { FieldValues, Path, UseFormSetError } from "react-hook-form";
import { z } from "zod";
import { ApiError, errorMessage } from "./api";

// Client-side checks mirror the backend for fast feedback; the backend stays authoritative.

export const optionalText = (max: number) =>
  z.string().trim().max(max, `Maksimal ${max} karakter.`);

export const npwp = z
  .string()
  .trim()
  .refine((value) => {
    if (!value) return true;
    const digits = value.replace(/[.\-\s]/g, "");
    return /^\d+$/.test(digits) && (digits.length === 15 || digits.length === 16);
  }, "NPWP harus terdiri dari 15 atau 16 digit.");

export const phone = z
  .string()
  .trim()
  .refine((value) => !value || /^[0-9+()\-\s.]{6,32}$/.test(value), "Nomor telepon tidak valid.");

export const optionalEmail = z
  .string()
  .trim()
  .refine((value) => !value || z.email().safeParse(value).success, "Format email tidak valid.");

/**
 * Accepts the Indonesian ways of writing a number when they cannot be misread, and returns the
 * plain form the API expects: "18,5" → "18.5", "1.250.000" → "1250000",
 * "1.250.000,50" → "1250000.50". Anything else is returned unchanged for the validators to judge;
 * in particular "95.000" (95 or 95 thousand?) stays ambiguous and is refused by decimalString.
 */
export function normalizeDecimal(raw: string): string {
  const value = raw.trim().replace(/\s+/g, "");
  if (/^\d{1,3}(\.\d{3}){2,}(,\d+)?$/.test(value) || /^\d{1,3}\.\d{3},\d+$/.test(value)) {
    return value.replace(/\./g, "").replace(",", ".");
  }
  if (/^\d+,\d+$/.test(value)) return value.replace(",", ".");
  return value;
}

/** Non-negative decimal string with at most two fractional digits, normalized for the API. */
export const moneyString = z
  .string()
  .trim()
  .transform(normalizeDecimal)
  .refine((value) => !value || /^\d{1,18}(\.\d{1,2})?$/.test(value), {
    message: "Tulis angka seperti 1250000, 1.250.000, atau 1.250.000,50 (maks. 2 desimal).",
  });

export const percentString = z
  .string()
  .trim()
  .refine((value) => !value || (/^\d{1,3}(\.\d{1,2})?$/.test(value) && Number(value) <= 100), {
    message: "Persentase 0–100, maks. 2 desimal.",
  });

/** "" → null so optional fields are cleared rather than stored as empty strings. */
export function blankToNull<T extends Record<string, unknown>>(values: T): T {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(values)) {
    out[key] = typeof value === "string" && value.trim() === "" ? null : value;
  }
  return out as T;
}

/**
 * Maps a 422 response onto form fields. Returns a form-level message when the error could not
 * be attributed to a specific field (or is not a validation error at all).
 */
export function applyServerErrors<T extends FieldValues>(
  error: unknown,
  setError: UseFormSetError<T>,
  fields: readonly string[],
): string | null {
  if (error instanceof ApiError && error.status === 422) {
    const byField = error.fieldErrors();
    let unmatched = false;
    for (const [field, message] of Object.entries(byField)) {
      if (fields.includes(field)) setError(field as Path<T>, { type: "server", message });
      else unmatched = true;
    }
    if (Object.keys(byField).length > 0 && !unmatched) return null;
  }
  return errorMessage(error);
}

const AMBIGUOUS_THOUSANDS = /^[1-9]\d{0,2}\.\d{3}$/;

/**
 * Decimal string matching a NUMERIC(precision, scale) column, e.g. quantity (18,4) or unit
 * price (20,4). Sent to the API as-is; never converted to a JS number.
 */
export function decimalString(options: {
  integerDigits: number;
  fractionDigits: number;
  positive?: boolean;
  label: string;
}) {
  const pattern = new RegExp(
    String.raw`^\d{1,${options.integerDigits}}(\.\d{1,${options.fractionDigits}})?$`,
  );
  return z
    .string()
    .trim()
    .transform(normalizeDecimal)
    .refine((value) => value === "" || pattern.test(value), {
      message: `${options.label}: tulis angka seperti 1250000, 1.250.000, atau 18,5 (maks. ${options.fractionDigits} desimal).`,
    })
    // "95.000" reads as ninety-five thousand in Indonesian but would be stored as 95 — refuse to
    // guess (the spreadsheet import applies the same rule).
    .refine((value) => !AMBIGUOUS_THOUSANDS.test(value), {
      message: `${options.label} ambigu: "95.000" bisa berarti 95 atau 95 ribu. Tulis 95000 untuk sembilan puluh lima ribu, atau 95,0 bila memang desimal.`,
    })
    .refine((value) => !options.positive || value === "" || /[1-9]/.test(value), {
      message: `${options.label} harus lebih dari 0.`,
    });
}
