import { describe, expect, it } from "vitest";
import { toPayload } from "./ProjectForm";

const base = {
  number: "",
  name: "Gudang",
  project_type: "construction" as const,
  client_id: "",
  owner_id: "",
  location: "",
  start_date: "2026-11-01",
  end_date: "",
  currency: "IDR",
  budget_amount: "1250000000.50",
  tax_label: "PPN",
  tax_rate_percent: "11",
  description: "",
  scope: "",
  notes: "",
  attributes: [
    { key: "luas_bangunan_m2", value: "850" },
    { key: "material_utama", value: "baja" },
  ],
};

describe("ProjectForm toPayload", () => {
  it("keeps money as exact strings and blanks as null", () => {
    const payload = toPayload(base, false);
    expect(payload.budget_amount).toBe("1250000000.50");
    expect(payload.tax_rate_percent).toBe("11");
    expect(payload.client_id).toBeNull();
    expect(payload.end_date).toBeNull();
    expect(payload.attributes).toEqual({ luas_bangunan_m2: "850", material_utama: "baja" });
  });

  it("requests automatic numbering when the number is blank on create", () => {
    expect(toPayload(base, false).number).toBeNull();
    expect(toPayload({ ...base, number: " KONTRAK/7 " }, false).number).toBe("KONTRAK/7");
  });

  it("never sends the number on edit (it is immutable in the form)", () => {
    expect(toPayload({ ...base, number: "X" }, true)).not.toHaveProperty("number");
  });
});
