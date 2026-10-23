import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { CatalogItemDetail as Detail, ImportJob, PriceObservation } from "@/lib/types";
import { renderAs } from "@/test/render";
import { CatalogItemDetail } from "./CatalogItemDetail";
import { catalogItemPayload, catalogItemSchema, type CatalogItemValues } from "./CatalogItemFormDialog";
import { ImportPreview } from "./CatalogImportPage";
import { observationSchema, type ObservationValues } from "./ObservationFormDialog";
import { SourceLink } from "./PriceBits";
import { VerificationDialog } from "./VerificationDialog";

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "ci1" }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function observation(overrides: Partial<PriceObservation> = {}): PriceObservation {
  return {
    id: "obs1",
    catalog_item_id: "ci1",
    price: "65000.0000",
    currency: "IDR",
    unit: "sak",
    supplier: { id: "s1", name: "TB Maju" },
    source_type: "vendor_quote",
    source_reference: "PH-12",
    source_url: null,
    observed_specification: null,
    match_level: null,
    observed_at: "2026-10-01",
    valid_from: null,
    valid_until: null,
    location: null,
    verification_status: "unverified",
    verified_by: null,
    verified_at: null,
    verification_note: null,
    notes: null,
    import_job_id: null,
    created_at: "2026-10-01T03:00:00Z",
    ...overrides,
  };
}

const baseObservation: ObservationValues = {
  price: "65000",
  currency: "IDR",
  supplier_id: "",
  source_type: "manual",
  source_reference: "",
  source_url: "",
  observed_at: "2026-10-19",
  valid_from: "",
  valid_until: "",
  location: "",
  observed_specification: "",
  notes: "",
};

describe("observation form rules", () => {
  const issues = (values: Partial<ObservationValues>) =>
    observationSchema.safeParse({ ...baseObservation, ...values }).error?.issues.map((i) => i.path.join(".")) ?? [];

  it("accepts a plain manual price", () => {
    expect(issues({})).toEqual([]);
  });

  it("requires a price and refuses ambiguous dot-thousands", () => {
    expect(issues({ price: "" })).toContain("price");
    expect(issues({ price: "4.500" })).toContain("price");
    expect(issues({ price: "4500.75" })).toEqual([]);
  });

  it("only takes http(s) source URLs and requires one for external sources", () => {
    expect(issues({ source_url: "javascript:alert(1)" })).toContain("source_url");
    expect(issues({ source_type: "external" })).toContain("source_url");
    expect(issues({ source_type: "external", source_url: "https://toko.example/semen" })).toEqual([]);
  });

  it("keeps the validity window ordered", () => {
    expect(issues({ valid_from: "2026-10-10", valid_until: "2026-10-01" })).toContain("valid_until");
    expect(issues({ valid_until: "2026-10-01" })).toContain("valid_until"); // before observed_at
  });
});

describe("catalog item payload", () => {
  const values: CatalogItemValues = {
    code: "",
    name: "Semen Portland",
    category: "Material",
    brand: "",
    specification: "",
    unit: "sak",
    item_type: "material",
    notes: "",
    is_active: true,
    price: "",
    observed_at: "2026-10-19",
    supplier_id: "",
    source_reference: "",
    source_url: "",
  };

  it("creates without a price when none is entered", () => {
    const payload = catalogItemPayload(values, false);
    expect(payload).toMatchObject({ name: "Semen Portland", code: null, brand: null });
    expect(payload).not.toHaveProperty("initial_price");
    expect(payload).not.toHaveProperty("is_active");
  });

  it("turns an entered price into the first (unverified) observation", () => {
    const payload = catalogItemPayload({ ...values, price: "65000", source_reference: "PH-12" }, false);
    expect(payload.initial_price).toEqual({
      price: "65000",
      currency: "IDR",
      observed_at: "2026-10-19",
      supplier_id: null,
      source_reference: "PH-12",
      source_url: null,
      source_type: "manual",
    });
  });

  it("never sends a price when editing", () => {
    const payload = catalogItemPayload({ ...values, price: "1", is_active: false }, true);
    expect(payload).not.toHaveProperty("initial_price");
    expect(payload).toMatchObject({ is_active: false });
  });

  it("requires a date with a price", () => {
    const result = catalogItemSchema.safeParse({ ...values, price: "65000", observed_at: "" });
    expect(result.error?.issues.map((i) => i.path.join("."))).toContain("observed_at");
  });
});

describe("SourceLink", () => {
  it("renders http(s) links without leaking the referrer", () => {
    render(<SourceLink url="https://toko.example/semen?id=1" />);
    const link = screen.getByRole("link", { name: /toko\.example/ });
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("drops anything else", () => {
    const { container } = render(<SourceLink url="javascript:alert(1)" />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("VerificationDialog", () => {
  it("requires a reason to reject", async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    render(
      <VerificationDialog
        target={{ observation: observation(), status: "rejected" }}
        onClose={vi.fn()}
        onConfirm={onConfirm}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Tolak" }));
    expect(await screen.findByText("Alasan penolakan wajib diisi.")).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();

    await userEvent.type(screen.getByLabelText(/alasan penolakan/i), "Harga kedaluwarsa");
    await userEvent.click(screen.getByRole("button", { name: "Tolak" }));
    expect(onConfirm).toHaveBeenCalledWith("rejected", "Harga kedaluwarsa");
  });

  it("cannot verify a price without any source", () => {
    render(
      <VerificationDialog
        target={{
          observation: observation({ supplier: null, source_reference: null, source_url: null }),
          status: "verified",
        }}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Verifikasi" })).toBeDisabled();
    expect(screen.getByText(/tanpa sumber tidak dapat diverifikasi/i)).toBeInTheDocument();
  });
});

function job(overrides: Partial<ImportJob> = {}): ImportJob {
  return {
    id: "j1",
    status: "previewed",
    filename: "harga.xlsx",
    row_count: 2,
    valid_count: 1,
    error_count: 1,
    warnings: ["Kolom tidak dikenal diabaikan: diskon."],
    rows: [
      {
        row: 2,
        valid: true,
        errors: [],
        action: "create_item",
        data: { name: "Semen", unit: "sak", price: "65000", currency: "IDR", observed_at: "2026-10-01" },
      },
      {
        row: 3,
        valid: false,
        errors: ["harga: format ambigu “4.500”."],
        action: null,
        data: { name: "Pasir", unit: "m3", price: null },
      },
    ],
    result: null,
    created_at: "2026-10-19T00:00:00Z",
    committed_at: null,
    ...overrides,
  };
}

describe("ImportPreview", () => {
  it("shows what will happen to each row and only commits valid ones", async () => {
    const onCommit = vi.fn();
    render(<ImportPreview job={job()} busy={null} onCommit={onCommit} onDiscard={vi.fn()} onRestart={vi.fn()} />);

    expect(screen.getByText("Kolom tidak dikenal diabaikan: diskon.")).toBeInTheDocument();
    const bad = screen.getByText("Pasir").closest("tr")!;
    expect(within(bad).getByText("Dilewati")).toBeInTheDocument();
    expect(within(bad).getByText(/format ambigu/)).toBeInTheDocument();
    expect(within(screen.getByText("Semen").closest("tr")!).getByText("Item baru")).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText(/hanya baris bermasalah/i));
    expect(screen.queryByText("Semen")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Simpan 1 baris valid" }));
    expect(onCommit).toHaveBeenCalled();
  });

  it("cannot commit when nothing is valid, and reports the result after commit", () => {
    const { rerender } = render(
      <ImportPreview job={job({ valid_count: 0 })} busy={null} onCommit={vi.fn()} onDiscard={vi.fn()} onRestart={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Simpan 0 baris valid" })).toBeDisabled();

    rerender(
      <ImportPreview
        job={job({ status: "committed", result: { items_created: 1, prices_created: 1, suppliers_created: 0 } })}
        busy={null}
        onCommit={vi.fn()}
        onDiscard={vi.fn()}
        onRestart={vi.fn()}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("1 item baru, 1 harga, dan 0 supplier baru disimpan.");
    expect(screen.queryByRole("button", { name: /simpan/i })).toBeNull();
  });
});

describe("CatalogItemDetail", () => {
  const detail: Detail = {
    id: "ci1",
    code: "MAT-001",
    name: "Semen Portland",
    category: "Material",
    brand: "Tiga Roda",
    specification: "50 kg",
    unit: "sak",
    item_type: "material",
    is_active: true,
    notes: null,
    version: 2,
    updated_at: "2026-10-19T00:00:00Z",
    prices: { latest_verified: null, latest_any: observation(), observation_count: 2 },
    observations: [
      observation(),
      observation({
        id: "obs0",
        price: "60000.0000",
        observed_at: "2026-09-01",
        verification_status: "rejected",
        verification_note: "Kedaluwarsa",
      }),
    ],
  };

  function mockApi() {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const body = url.includes("/audit-logs") ? { items: [], total: 0, page: 1, page_size: 10 } : detail;
        return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
  }

  it("lists the full price history and offers verification only to verifiers", async () => {
    mockApi();
    const { unmount } = renderAs(["pricing.read", "pricing.verify"], <CatalogItemDetail />);
    const table = await screen.findByRole("table", { name: "Riwayat harga" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("button", { name: "Verifikasi harga" })).toBeInTheDocument();
    // A rejected price stays in the history but cannot be acted on again.
    expect(within(rows[1]).queryByRole("button")).toBeNull();
    expect(within(rows[1]).getByText("“Kedaluwarsa”")).toBeInTheDocument();
    expect(screen.getByText("Belum ada harga yang diverifikasi untuk item ini.")).toBeInTheDocument();
    unmount();

    mockApi();
    renderAs(["pricing.read"], <CatalogItemDetail />);
    await screen.findByRole("table", { name: "Riwayat harga" });
    expect(screen.queryByRole("button", { name: "Verifikasi harga" })).toBeNull();
    expect(screen.queryByRole("button", { name: /catat harga/i })).toBeNull();
  });
});
