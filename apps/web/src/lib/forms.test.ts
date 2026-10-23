import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { applyServerErrors, blankToNull, decimalString, moneyString, normalizeDecimal, npwp, percentString, phone } from "./forms";

describe("validators", () => {
  it.each(["", "0", "1250000", "1250000.5", "1250000.50", "1.250.000", "1,5"])("money accepts %p", (value) => {
    expect(moneyString.safeParse(value).success).toBe(true);
  });

  it.each(["1.005", "1,250.50", "-1", "1e6", "abc"])("money rejects %p", (value) => {
    expect(moneyString.safeParse(value).success).toBe(false);
  });

  it("percent is bounded to 0–100", () => {
    expect(percentString.safeParse("11").success).toBe(true);
    expect(percentString.safeParse("100").success).toBe(true);
    expect(percentString.safeParse("100.01").success).toBe(false);
  });

  it("NPWP accepts 15 or 16 digits with separators", () => {
    expect(npwp.safeParse("01.234.567.8-901.000").success).toBe(true);
    expect(npwp.safeParse("0123456789012345").success).toBe(true);
    expect(npwp.safeParse("12345").success).toBe(false);
    expect(npwp.safeParse("").success).toBe(true);
  });

  it("phone allows common formats only", () => {
    expect(phone.safeParse("+62 21-555 1234").success).toBe(true);
    expect(phone.safeParse("<script>").success).toBe(false);
  });
});

describe("blankToNull", () => {
  it("turns blank strings into null and leaves other values", () => {
    expect(blankToNull({ a: "", b: "  ", c: "x", d: 0, e: false })).toEqual({
      a: null,
      b: null,
      c: "x",
      d: 0,
      e: false,
    });
  });
});

describe("applyServerErrors", () => {
  const validation = new ApiError(422, {
    code: "validation_error",
    message: "Data yang dikirim tidak valid.",
    details: [{ loc: ["body", "name"], msg: "Nama wajib" }],
    request_id: null,
  });

  it("puts field errors on known fields and returns no form message", () => {
    const setError = vi.fn();
    expect(applyServerErrors(validation, setError, ["name"])).toBeNull();
    expect(setError).toHaveBeenCalledWith("name", { type: "server", message: "Nama wajib" });
  });

  it("falls back to a form message for unknown fields and other errors", () => {
    const setError = vi.fn();
    expect(applyServerErrors(validation, setError, ["email"])).toBe("Data yang dikirim tidak valid.");
    const conflict = new ApiError(409, {
      code: "version_conflict",
      message: "Data telah diubah oleh pengguna lain.",
      details: null,
      request_id: null,
    });
    expect(applyServerErrors(conflict, setError, ["name"])).toBe("Data telah diubah oleh pengguna lain.");
  });
});

describe("Indonesian number input", () => {
  it("normalizes unambiguous Indonesian notation for the API", () => {
    expect(normalizeDecimal("18,5")).toBe("18.5");
    expect(normalizeDecimal(" 1.250.000 ")).toBe("1250000");
    expect(normalizeDecimal("1.250.000,50")).toBe("1250000.50");
    expect(normalizeDecimal("1.250,5")).toBe("1250.5");
    expect(normalizeDecimal("1250000.50")).toBe("1250000.50");
    expect(normalizeDecimal("95.000")).toBe("95.000"); // ambiguous: left for the validator
    expect(normalizeDecimal("1,250.50")).toBe("1,250.50"); // English notation is not guessed
  });

  it("accepts what it can read and refuses what it cannot", () => {
    const price = decimalString({ integerDigits: 16, fractionDigits: 4, label: "Harga" });
    expect(price.parse("1.250.000")).toBe("1250000");
    expect(price.parse("4.300,75")).toBe("4300.75");
    expect(price.safeParse("95.000").error?.issues[0]?.message).toMatch(/ambigu/);
    expect(price.safeParse("1,250.50").success).toBe(false);
    const quantity = decimalString({ integerDigits: 14, fractionDigits: 4, positive: true, label: "Volume" });
    expect(quantity.parse("18,5")).toBe("18.5");
    expect(quantity.safeParse("0,0").success).toBe(false);
    expect(moneyString.parse("1.500.000")).toBe("1500000");
  });
});
