import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { formatQuantity, formatUnitPrice } from "@/lib/format";
import { decimalString } from "@/lib/forms";
import type { PriceCandidate, RabItem, RabVersion } from "@/lib/types";
import { renderAs } from "@/test/render";
import { ItemFormDialog, itemPayload, trimZeros } from "./ItemFormDialog";
import { IssuesCard, ItemsTable, TotalsCard } from "./RabPanels";
import { TransitionDialog } from "./TransitionDialog";

const plain = (text: string | null) => (text ?? "").replace(/ /g, " ");

const item: RabItem = {
  id: "i1",
  position: 1,
  code: "M-01",
  name: "Semen",
  category: "Struktur",
  item_type: "material",
  specification: null,
  quantity: "10.0000",
  unit: "sak",
  unit_price: "65000.0000",
  subtotal: "650000.00",
  price_source_type: "manual",
  price_source: "Toko A",
  notes: null,
  row_version: 1,
  price_observation_id: null,
  price_verification_status: null,
};

function version(overrides: Partial<RabVersion> = {}): RabVersion {
  return {
    id: "v1",
    version_no: 1,
    status: "draft",
    grand_total: "721500.00",
    currency: "IDR",
    created_at: "2026-10-18T00:00:00Z",
    decided_at: null,
    based_on_version_id: null,
    tax_label: "PPN",
    tax_rate_percent: "11.00",
    discount_type: "none",
    discount_value: "0.00",
    notes: null,
    assumptions: null,
    totals: {
      subtotal: "650000.00",
      discount_amount: "0.00",
      taxable_base: "650000.00",
      tax_amount: "71500.00",
      grand_total: "721500.00",
      unpriced_items: 0,
    },
    items: [item],
    issues: [],
    approvals: [],
    submitted_by: null,
    submitted_at: null,
    decided_by: null,
    lock_version: 3,
    editable: true,
    allowed_actions: ["submit", "archive"],
    can_create_version: false,
    ...overrides,
  };
}

describe("decimal inputs", () => {
  const quantity = decimalString({ integerDigits: 14, fractionDigits: 4, positive: true, label: "Kuantitas" });

  it.each(["1", "2.5", "0.0001", "12345678901234.1234", "1,5", "1.500.000"])("accepts %p", (value) => {
    expect(quantity.safeParse(value).success).toBe(true);
  });

  // Regression: the pattern once lost its backslashes and matched letters instead of digits.
  it.each(["d", "dd.d", "0", "0.0000", "0,0", "1.23456", "-1", "1e3", "123456789012345", "95.000", "1.500", "1,250.5"])(
    "rejects %p",
    (value) => {
      expect(quantity.safeParse(value).success).toBe(false);
    },
  );

  it("refuses dot-thousands instead of storing 95.000 as 95", () => {
    expect(quantity.safeParse("95.000").error?.issues[0].message).toMatch(/ambigu/);
    expect(quantity.safeParse("0.125").success).toBe(true);
    expect(quantity.safeParse("95.0").success).toBe(true);
  });

  it("trims NUMERIC trailing zeros for editing", () => {
    expect(trimZeros("10.0000")).toBe("10");
    expect(trimZeros("2.5000")).toBe("2.5");
    expect(trimZeros("1200")).toBe("1200");
  });

  it("formats quantity and 4-decimal unit prices without losing digits", () => {
    expect(formatQuantity("2.5000")).toBe("2,5");
    expect(plain(formatUnitPrice("33.3350"))).toBe("Rp 33,335");
    expect(plain(formatUnitPrice("65000.0000"))).toBe("Rp 65.000");
  });
});

describe("ItemFormDialog", () => {
  it("validates and sends decimals as strings, blanks as null", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderAs([], <ItemFormDialog open item={null} onClose={vi.fn()} onSubmit={onSubmit} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/nama item/i), "Besi beton");
    await user.type(screen.getByLabelText(/kuantitas/i), "0");
    await user.type(screen.getByLabelText(/^satuan/i), "batang");
    await user.type(screen.getByLabelText(/harga satuan/i), "95.000");
    await user.click(screen.getByRole("button", { name: "Tambah item" }));

    expect(await screen.findByText("Kuantitas harus lebih dari 0.")).toBeInTheDocument();
    expect(screen.getByText(/Harga satuan ambigu/)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText(/kuantitas/i));
    await user.type(screen.getByLabelText(/kuantitas/i), "20");
    await user.clear(screen.getByLabelText(/harga satuan/i));
    await user.type(screen.getByLabelText(/harga satuan/i), "95000");
    await user.click(screen.getByRole("button", { name: "Tambah item" }));

    await vi.waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      name: "Besi beton",
      quantity: "20",
      unit: "batang",
      unit_price: "95000",
      code: null,
      price_source_type: null,
      price_observation_id: null,
    });
  });

  it("prefills an existing item without NUMERIC padding", () => {
    renderAs([], <ItemFormDialog open item={item} onClose={vi.fn()} onSubmit={vi.fn()} />);
    expect(screen.getByLabelText(/kuantitas/i)).toHaveValue("10");
    expect(screen.getByLabelText(/harga satuan/i)).toHaveValue("65000");
  });

  it("builds payloads without inventing values", () => {
    expect(
      itemPayload({
        name: "X",
        code: "",
        category: "",
        item_type: "service",
        specification: "",
        quantity: "1",
        unit: "ls",
        unit_price: "",
        price_source_type: "",
        price_source: "",
        notes: "",
        price_observation_id: "",
      }),
    ).toMatchObject({ unit_price: null, price_source: null, quantity: "1", price_observation_id: null });
  });
});

function candidate(overrides: Partial<PriceCandidate>): PriceCandidate {
  return {
    kind: "catalog",
    score: 88,
    level: "high",
    unit_compatible: true,
    reasons: ["Nama sangat mirip."],
    warnings: [],
    name: "Semen Portland 50 kg",
    unit: "sak",
    brand: "Tiga Roda",
    specification: null,
    price: "65000.0000",
    currency: "IDR",
    observed_at: "2026-10-01",
    verified: true,
    catalog_item_id: "ci1",
    observation_id: "obs1",
    supplier: "TB Maju",
    source_reference: "PH-12",
    reference: null,
    ...overrides,
  };
}

function respond(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("ItemFormDialog price search", () => {
  async function openSearch(candidates: PriceCandidate[]) {
    const fetchMock = vi.fn().mockResolvedValue(respond(candidates));
    vi.stubGlobal("fetch", fetchMock);
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    renderAs(["pricing.read"], <ItemFormDialog open item={null} onClose={vi.fn()} onSubmit={onSubmit} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/nama item/i), "Semen 50 kg");
    await user.type(screen.getByLabelText(/kuantitas/i), "10");
    await user.type(screen.getByLabelText(/^satuan/i), "sak");
    await user.click(screen.getByRole("button", { name: /cari harga/i }));
    return { fetchMock, onSubmit, user };
  }

  it("is hidden without pricing.read", () => {
    renderAs([], <ItemFormDialog open item={null} onClose={vi.fn()} onSubmit={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /cari harga/i })).toBeNull();
  });

  it("links a catalog price and lets the server resolve it", async () => {
    const { fetchMock, onSubmit, user } = await openSearch([
      candidate({}),
      candidate({ observation_id: "obs2", name: "Semen curah", unit: "kg", unit_compatible: false, level: "low" }),
    ]);

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/price-catalog/candidates?");
    expect(url).toContain("name=Semen+50+kg");
    expect(url).toContain("unit=sak");
    expect(await screen.findByText("Semen Portland 50 kg")).toBeInTheDocument();
    // A unit mismatch can be seen but never applied.
    expect(screen.getByRole("button", { name: "Gunakan harga Semen curah" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Gunakan harga Semen Portland 50 kg" }));
    expect(screen.getByText("Harga dari katalog (dikunci)")).toBeInTheDocument();
    expect(screen.queryByLabelText(/harga satuan/i)).toBeNull();

    await user.click(screen.getByRole("button", { name: "Tambah item" }));
    await vi.waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      price_observation_id: "obs1",
      price_source_type: "catalog",
      unit_price: "65000",
    });
  });

  it("copies an approved-RAB price as history, without a catalog link", async () => {
    const { onSubmit, user } = await openSearch([
      candidate({ kind: "history", observation_id: null, catalog_item_id: null, verified: false, reference: "RAB-2026-0001 v1 (disetujui)" }),
    ]);
    await user.click(await screen.findByRole("button", { name: /gunakan harga/i }));

    expect(screen.getByLabelText(/harga satuan/i)).toHaveValue("65000");
    expect(screen.getByLabelText(/^sumber harga/i)).toHaveValue("RAB-2026-0001 v1 (disetujui)");
    await user.click(screen.getByRole("button", { name: "Tambah item" }));
    await vi.waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0]).toMatchObject({ price_observation_id: null, price_source_type: "history" });
  });

  it("unlinking clears the borrowed price", async () => {
    const linkedItem = { ...item, price_observation_id: "obs1", price_source_type: "catalog" as const, price_verification_status: "unverified" as const };
    renderAs(["pricing.read"], <ItemFormDialog open item={linkedItem} onClose={vi.fn()} onSubmit={vi.fn()} />);
    expect(screen.getByText("Belum terverifikasi")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /lepas tautan/i }));
    expect(screen.getByLabelText(/harga satuan/i)).toHaveValue("");
    expect(screen.getByLabelText(/^sumber harga/i)).toHaveValue("");
  });
});

describe("RAB panels", () => {
  it("shows server totals verbatim, including tax after discount", () => {
    render(
      <TotalsCard
        version={version({
          discount_type: "percent",
          discount_value: "10.00",
          totals: {
            subtotal: "1400000.00",
            discount_amount: "140000.00",
            taxable_base: "1260000.00",
            tax_amount: "138600.00",
            grand_total: "1398600.00",
            unpriced_items: 2,
          },
        })}
      />,
    );
    const text = plain(document.body.textContent);
    expect(text).toContain("Diskon 10%");
    expect(text).toContain("− Rp 140.000");
    expect(text).toContain("PPN 11%");
    expect(text).toContain("Rp 138.600");
    expect(text).toContain("Rp 1.398.600");
    expect(text).toContain("2 item belum memiliki harga");
  });

  it("labels unconfigured tax honestly", () => {
    render(<TotalsCard version={version({ tax_label: null, tax_rate_percent: null })} />);
    expect(screen.getByText("Pajak (belum dikonfigurasi)")).toBeInTheDocument();
  });

  it("flags unpriced items and hides edit controls on locked versions", () => {
    const unpriced = { ...item, id: "i2", name: "Kabel", unit_price: null, subtotal: null };
    const { rerender } = render(
      <ItemsTable version={version({ items: [item, unpriced] })} onEdit={vi.fn()} onDelete={vi.fn()} />,
    );
    const row = screen.getByText("Kabel").closest("tr")!;
    expect(within(row).getByText("Belum ada harga")).toBeInTheDocument();
    expect(screen.queryByText("Terverifikasi")).toBeNull();
    expect(screen.getAllByRole("button", { name: /^ubah/i })).toHaveLength(2);

    rerender(<ItemsTable version={version({ status: "approved", editable: false })} onEdit={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /^ubah/i })).toBeNull();
  });

  it("summarises blocking errors", () => {
    render(
      <IssuesCard
        issues={[
          { severity: "error", code: "missing_price", message: "Item 2 (Kabel) belum memiliki harga satuan.", item_id: "i2" },
          { severity: "warning", code: "missing_price_source", message: "Tanpa sumber", item_id: "i1" },
        ]}
      />,
    );
    expect(screen.getByText(/1 kesalahan harus diperbaiki/)).toBeInTheDocument();
  });
});

describe("TransitionDialog", () => {
  it("requires a note to reject", async () => {
    const onConfirm = vi.fn();
    render(<TransitionDialog action="reject" versionNo={1} onClose={vi.fn()} onConfirm={onConfirm} />);

    await userEvent.click(screen.getByRole("button", { name: "Tolak" }));
    expect(await screen.findByText("Wajib diisi.")).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();

    await userEvent.type(screen.getByLabelText(/alasan penolakan/i), "Harga terlalu tinggi");
    await userEvent.click(screen.getByRole("button", { name: "Tolak" }));
    expect(onConfirm).toHaveBeenCalledWith("reject", "Harga terlalu tinggi");
  });

  it("lists the validation errors that block submission", async () => {
    const onClose = vi.fn();
    const onConfirm = vi.fn().mockRejectedValue(
      new ApiError(422, {
        code: "validation_error",
        message: "RAB belum dapat diajukan.",
        details: {
          issues: [
            { severity: "error", code: "missing_price", message: "Item 1 (Kabel) belum memiliki harga satuan.", item_id: "i" },
            { severity: "info", code: "no_tax", message: "Pajak belum dikonfigurasi", item_id: null },
          ],
        },
        request_id: null,
      }),
    );
    render(<TransitionDialog action="submit" versionNo={1} onClose={onClose} onConfirm={onConfirm} />);

    await userEvent.click(screen.getByRole("button", { name: "Ajukan review" }));

    expect(await screen.findByText("Item 1 (Kabel) belum memiliki harga satuan.")).toBeInTheDocument();
    expect(screen.queryByText("Pajak belum dikonfigurasi")).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("catalog-linked items", () => {
  it("show the catalog price verification status", () => {
    const linked = { ...item, price_observation_id: "obs1", price_source_type: "catalog" as const, price_verification_status: "verified" as const };
    render(<ItemsTable version={version({ items: [linked] })} onEdit={vi.fn()} />);
    expect(screen.getByText("Terverifikasi")).toBeInTheDocument();
  });
});
