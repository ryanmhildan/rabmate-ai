import { describe, expect, it } from "vitest";
import { formatPercent, formatRupiah, formatTanggal, formatTanggalWaktu } from "./format";

// Intl inserts a non-breaking space after "Rp"; normalise for readable assertions.
const plain = (text: string) => text.replace(/ /g, " ");

describe("formatRupiah", () => {
  it("formats whole rupiah without decimals", () => {
    expect(plain(formatRupiah("1250000"))).toBe("Rp 1.250.000");
  });

  it("shows cents with exactly two decimals using Indonesian separators", () => {
    expect(plain(formatRupiah("1250000.5"))).toBe("Rp 1.250.000,50");
    expect(plain(formatRupiah("1250000.55"))).toBe("Rp 1.250.000,55");
    expect(plain(formatRupiah("1250000.00"))).toBe("Rp 1.250.000");
  });

  it("does not lose precision beyond Number.MAX_SAFE_INTEGER", () => {
    expect(plain(formatRupiah("123456789012345678.25"))).toBe(
      "Rp 123.456.789.012.345.678,25",
    );
  });

  it("formats negative values", () => {
    expect(plain(formatRupiah("-5000"))).toBe("-Rp 5.000");
  });

  it.each([null, undefined, "", "abc", "1e5", "1,5", "NaN"])("rejects %p", (value) => {
    expect(formatRupiah(value)).toBe("-");
  });
});

describe("formatTanggal", () => {
  it("renders the calendar date in Asia/Jakarta, not UTC", () => {
    // 18:30 UTC on 17 Oct is already 18 Oct in Jakarta (UTC+7).
    expect(formatTanggal("2026-10-17T18:30:00Z")).toBe("18 Oktober 2026");
  });

  it("handles invalid and missing input", () => {
    expect(formatTanggal("not a date")).toBe("-");
    expect(formatTanggal(null)).toBe("-");
  });
});

describe("formatTanggalWaktu", () => {
  it("includes Jakarta time and zone", () => {
    const text = plain(formatTanggalWaktu("2026-10-18T13:30:00Z"));
    expect(text).toContain("18 Okt 2026");
    expect(text).toContain("20.30");
    expect(text).toContain("WIB");
  });
});

describe("formatPercent", () => {
  it("trims trailing zeros and uses a decimal comma", () => {
    expect(formatPercent("11.00")).toBe("11%");
    expect(formatPercent("11.50")).toBe("11,5%");
    expect(formatPercent("x")).toBe("-");
  });
});
