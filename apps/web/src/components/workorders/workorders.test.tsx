import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApprovalQueuePage } from "@/components/approvals/ApprovalQueuePage";
import { DocumentDetail } from "@/components/documents/DocumentDetail";
import { ApiError } from "@/lib/api";
import { renderAs } from "@/test/render";
import { applyLineErrors, bastFormSchema, bastPayload, type BastFormValues } from "./BastDetail";
import { spkFormSchema, spkPayload, type SpkFormValues } from "./SpkDetail";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "d1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const spkValues: SpkFormValues = {
  title: "Instalasi jaringan",
  start_date: "2026-10-26",
  end_date: "2026-11-25",
  location: "",
  scope: "Penarikan kabel",
  terms: "  ",
  notes: "",
  client_signatory_name: "Budi Santoso",
  client_signatory_title: "",
  company_signatory_name: "Sari Wulandari",
  company_signatory_title: "Manajer Proyek",
};

describe("SPK form", () => {
  it("refuses an end date before the start date", () => {
    const result = spkFormSchema.safeParse({ ...spkValues, end_date: "2026-10-01" });
    expect(result.success).toBe(false);
    expect(result.error?.issues[0]).toMatchObject({ path: ["end_date"] });
    expect(spkFormSchema.safeParse({ ...spkValues, end_date: "" }).success).toBe(true);
  });

  it("sends blanks as null with the version it read", () => {
    expect(spkPayload({ version: 3 }, spkValues)).toMatchObject({
      version: 3,
      location: null,
      terms: null,
      client_signatory_title: null,
      company_signatory_title: "Manajer Proyek",
    });
  });
});

const bastValues: BastFormValues = {
  title: "Serah terima tahap 1",
  handover_date: "2026-10-19",
  location: "",
  delivered_by_name: "Sari",
  delivered_by_title: "",
  received_by_name: "Budi",
  received_by_title: "",
  terms: "",
  notes: "",
  items: [
    { rab_item_id: "i1", description: "Kabel UTP", quantity: "200", unit: "m", condition: " Terpasang " },
    { rab_item_id: "", description: "Patch panel tambahan", quantity: "1", unit: "unit", condition: "" },
  ],
};

describe("BAST form", () => {
  it("maps free lines and blank conditions to null", () => {
    expect(bastPayload({ version: 2 }, bastValues)).toEqual({
      title: "Serah terima tahap 1",
      handover_date: "2026-10-19",
      location: null,
      delivered_by_name: "Sari",
      delivered_by_title: null,
      received_by_name: "Budi",
      received_by_title: null,
      terms: null,
      notes: null,
      version: 2,
      items: [
        { rab_item_id: "i1", description: "Kabel UTP", quantity: "200", unit: "m", condition: "Terpasang" },
        { rab_item_id: null, description: "Patch panel tambahan", quantity: "1", unit: "unit", condition: null },
      ],
    });
  });

  it("rejects a contract item twice, zero and ambiguous volumes", () => {
    const twice = bastFormSchema.safeParse({
      ...bastValues,
      items: [bastValues.items[0], { ...bastValues.items[0], quantity: "5" }],
    });
    expect(twice.success).toBe(false);
    expect(twice.error?.issues[0].message).toMatch(/hanya boleh muncul sekali/);
    const zero = bastFormSchema.safeParse({ ...bastValues, items: [{ ...bastValues.items[0], quantity: "0" }] });
    expect(zero.error?.issues[0].message).toMatch(/lebih dari 0/);
    const ambiguous = bastFormSchema.safeParse({ ...bastValues, items: [{ ...bastValues.items[0], quantity: "1.000" }] });
    expect(ambiguous.error?.issues[0].message).toMatch(/ambigu/);
  });

  it("puts the server's per-line errors on the matching inputs", () => {
    const setError = vi.fn();
    const error = new ApiError(422, {
      code: "validation_error",
      message: "Volume serah terima tidak sesuai dengan kontrak.",
      details: [
        { loc: ["body", "items", 1, "quantity"], msg: "Melebihi sisa volume kontrak (105 m)." },
        { loc: ["body", "handover_date"], msg: "Tidak boleh di masa depan." },
      ],
      request_id: null,
    });
    expect(applyLineErrors(error, setError)).toBe(true);
    expect(setError).toHaveBeenCalledTimes(1);
    expect(setError).toHaveBeenCalledWith("items.1.quantity", {
      type: "server",
      message: "Melebihi sisa volume kontrak (105 m).",
    });
    expect(applyLineErrors(new Error("x"), setError)).toBe(false);
  });
});

const page = <T,>(items: T[]) => ({ items, total: items.length, page: 1, page_size: 100 });

describe("ApprovalQueuePage", () => {
  it("lists every document type waiting for review for document approvers", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.startsWith("/api/v1/spk?"))
        return Promise.resolve(
          json(200, page([{ id: "s1", number: null, title: "Instalasi jaringan", project: { name: "Kantor Cabang" }, contract_value: "10779765.00", currency: "IDR" }])),
        );
      if (url.startsWith("/api/v1/bast?"))
        return Promise.resolve(json(200, page([{ id: "b1", number: null, title: "Serah terima tahap 1", project: { name: "Kantor Cabang" } }])));
      return Promise.resolve(json(200, page([])));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderAs(["documents.approve", "projects.read"], <ApprovalQueuePage />);

    expect(await screen.findByRole("link", { name: "Instalasi jaringan" })).toHaveAttribute("href", "/spk-bast/spk/s1");
    expect(screen.getByRole("link", { name: "Serah terima tahap 1" })).toHaveAttribute("href", "/spk-bast/bast/b1");
    expect(screen.getByText("Rp 10.779.765")).toBeInTheDocument();
    const urls = fetchMock.mock.calls.map(([url]) => url);
    expect(urls.every((u) => u.includes("status=in_review"))).toBe(true);
    expect(urls.some((u) => u.startsWith("/api/v1/approvals"))).toBe(false); // no rab.approve
  });
});

describe("DocumentDetail", () => {
  it("shows a non-RAB document with a link to its source instead of RAB fields", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          json(200, {
            id: "d1",
            doc_type: "spk",
            status: "issued",
            number: "SPK-2026-0001",
            title: "Instalasi jaringan",
            project_id: "p1",
            rab_version_id: null,
            quotation_id: null,
            invoice_id: null,
            spk_id: "s1",
            bast_id: null,
            currency: "IDR",
            total_amount: "10779765.00",
            snapshot_sha256: "a".repeat(64),
            schema_version: 1,
            issued_at: "2026-10-19T03:00:00Z",
            issued_by: null,
            voided_at: null,
            voided_by: null,
            void_reason: null,
            files: [],
            snapshot: {
              schema_version: 1,
              document: { number: "SPK-2026-0001", issued_at: "2026-10-19T03:00:00Z", issued_by: "Fina" },
              company: { name: "PT Alfa", legal_name: null },
              client: { name: "CV Klien Makmur" },
              project: { number: "PRJ-1", name: "Kantor Cabang" },
            },
          }),
        ),
      ),
    );
    renderAs(["documents.read", "documents.issue"], <DocumentDetail />);

    expect(await screen.findByRole("link", { name: "Buka SPK" })).toHaveAttribute("href", "/spk-bast/spk/s1");
    expect(screen.getByText("CV Klien Makmur")).toBeInTheDocument();
    // Voided from the SPK page (which also voids the SPK), not here.
    expect(screen.queryByRole("button", { name: /batalkan/i })).toBeNull();
  });
});
