import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RabImportPreview } from "@/components/rab/RabImportPage";
import { formatBytes } from "@/lib/documents";
import type { DocumentSettings, ImportJob, IssuedDocument, RabVersion } from "@/lib/types";
import { renderAs } from "@/test/render";
import { DocumentSettingsForm } from "./DocumentSettingsPanel";
import { IssueDocumentDialog } from "./IssueDocumentDialog";
import { RabDocumentsCard } from "./RabDocumentsCard";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const issued: IssuedDocument = {
  id: "d1",
  doc_type: "rab",
  status: "issued",
  number: "RAB-2026-0001/V1",
  title: "RAB Jaringan (versi 1)",
  project_id: "p1",
  rab_version_id: "v1",
  quotation_id: null,
  invoice_id: null,
  spk_id: null,
  bast_id: null,
  currency: "IDR",
  total_amount: "10779765.00",
  snapshot_sha256: "a".repeat(64),
  schema_version: 1,
  issued_at: "2026-10-19T03:00:00Z",
  issued_by: { id: "u1", email: "a@b.test", full_name: "Dewi" },
  voided_at: null,
  voided_by: null,
  void_reason: null,
  files: [],
};

describe("IssueDocumentDialog", () => {
  it("retries with the same idempotency key, so a retry cannot issue twice", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("network down"))
      .mockResolvedValueOnce(json(201, issued));
    vi.stubGlobal("fetch", fetchMock);
    const onIssued = vi.fn();
    const onClose = vi.fn();
    render(
      <IssueDocumentDialog
        open
        endpoint="/rab/r1/versions/1/documents"
        title="Terbitkan dokumen RAB"
        summary={<p>Versi 1 senilai Rp 10.779.765</p>}
        onClose={onClose}
        onIssued={onIssued}
      />,
    );
    expect(screen.getByText(/Rp\s10\.779\.765/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Terbitkan" }));
    expect(await screen.findByText(/Tidak dapat terhubung/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Terbitkan" }));

    await vi.waitFor(() => expect(onIssued).toHaveBeenCalledWith(issued));
    expect(onClose).toHaveBeenCalled();
    const keys = fetchMock.mock.calls.map(([, init]) => new Headers((init as RequestInit).headers).get("Idempotency-Key"));
    expect(keys[0]).toMatch(/^issue-[0-9a-f-]{36}$/);
    expect(keys[1]).toBe(keys[0]);
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/v1/rab/r1/versions/1/documents");
  });

  it("links to the document that is already issued", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        json(409, {
          error: {
            code: "already_issued",
            message: "Versi ini sudah memiliki dokumen terbit yang berlaku.",
            details: { document_id: "d9", number: "RAB-2026-0001/V1" },
            request_id: null,
          },
        }),
      ),
    );
    render(
      <IssueDocumentDialog open endpoint="/rab/r1/versions/1/documents" title="Terbitkan" summary="x" onClose={vi.fn()} onIssued={vi.fn()} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Terbitkan" }));
    expect(await screen.findByRole("link", { name: /lihat dokumen/i })).toHaveAttribute("href", "/dokumen/d9");
  });
});

function version(overrides: Partial<RabVersion> = {}): RabVersion {
  return {
    id: "v1",
    version_no: 1,
    status: "approved",
    grand_total: "100.00",
    currency: "IDR",
    created_at: "2026-10-18T00:00:00Z",
    decided_at: null,
    based_on_version_id: null,
    tax_label: null,
    tax_rate_percent: null,
    discount_type: "none",
    discount_value: "0.00",
    notes: null,
    assumptions: null,
    totals: {
      subtotal: "100.00",
      discount_amount: "0.00",
      taxable_base: "100.00",
      tax_amount: "0.00",
      grand_total: "100.00",
      unpriced_items: 0,
    },
    items: [],
    issues: [],
    approvals: [],
    submitted_by: null,
    submitted_at: null,
    decided_by: null,
    lock_version: 1,
    editable: false,
    allowed_actions: [],
    can_create_version: false,
    ...overrides,
  };
}

describe("RabDocumentsCard", () => {
  const page = (items: IssuedDocument[]) => json(200, { items, total: items.length, page: 1, page_size: 20 });

  it("offers issuing an approved version only to roles that may issue", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(page([]))));
    const { unmount } = renderAs(
      ["documents.read", "documents.issue", "rab.read"],
      <RabDocumentsCard rabId="r1" rabNumber="RAB-1" version={version()} />,
    );
    expect(await screen.findByRole("button", { name: /terbitkan dokumen/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /pratinjau pdf/i })).toHaveAttribute(
      "href",
      "/api/v1/rab/r1/versions/1/preview.pdf",
    );
    expect(screen.getByRole("link", { name: /ekspor xlsx/i })).toHaveAttribute("href", "/api/v1/rab/r1/versions/1/export.xlsx");
    expect(screen.queryByRole("link", { name: /impor item/i })).toBeNull(); // approved = not editable
    unmount();

    renderAs(["documents.read", "rab.read"], <RabDocumentsCard rabId="r1" rabNumber="RAB-1" version={version()} />);
    expect(await screen.findByText(/siap diterbitkan oleh pengguna/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /terbitkan dokumen/i })).toBeNull();
  });

  it("lists issued documents with stored-file links and no second issue button", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(page([issued]))));
    renderAs(["documents.read", "documents.issue"], <RabDocumentsCard rabId="r1" rabNumber="RAB-1" version={version()} />);
    const link = await screen.findByRole("link", { name: "RAB-2026-0001/V1" });
    expect(link).toHaveAttribute("href", "/dokumen/d1");
    expect(screen.getByRole("link", { name: /^pdf$/i })).toHaveAttribute("href", "/api/v1/documents/d1/files/pdf");
    expect(screen.queryByRole("button", { name: /terbitkan dokumen/i })).toBeNull();
  });

  it("links draft versions to the item import", () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(page([]))));
    renderAs(
      ["documents.read", "rab.write"],
      <RabDocumentsCard rabId="r1" rabNumber="RAB-1" version={version({ status: "draft", editable: true, version_no: 2 })} />,
    );
    expect(screen.getByRole("link", { name: /impor item/i })).toHaveAttribute("href", "/rab/r1/impor?versi=2");
    expect(screen.getByText(/setelah versi disetujui/i)).toBeInTheDocument();
  });
});

const settings: DocumentSettings = {
  tagline: null,
  accent_color: "#1F4E79",
  footer_text: null,
  rab_terms: null,
  show_item_codes: true,
  show_price_sources: false,
  show_amount_in_words: true,
  payment_bank_name: null,
  payment_account_number: null,
  payment_account_holder: null,
  spk_terms: null,
  bast_terms: null,
  version: 0,
  updated_at: null,
};

describe("DocumentSettingsForm", () => {
  it("validates and saves with the version it read, blanks as null", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(200, { ...settings, version: 1, tagline: "Andal" }));
    vi.stubGlobal("fetch", fetchMock);
    renderAs(["org.update", "documents.read"], <DocumentSettingsForm settings={settings} />);
    const user = userEvent.setup();

    const color = screen.getByLabelText(/^warna aksen/i);
    await user.clear(color);
    await user.type(color, "biru");
    await user.type(screen.getByLabelText(/nomor rekening/i), "12ab");
    await user.click(screen.getByRole("button", { name: "Simpan template" }));
    expect(await screen.findByText("Gunakan format warna #RRGGBB.")).toBeInTheDocument();
    expect(screen.getByText(/Hanya angka/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    await user.clear(color);
    await user.type(color, "#0F766E");
    await user.clear(screen.getByLabelText(/nomor rekening/i));
    await user.type(screen.getByLabelText(/tagline/i), "Andal");
    await user.type(screen.getByLabelText("Ketentuan SPK"), "Pekerjaan dimulai setelah uang muka diterima.");
    await user.click(screen.getByRole("button", { name: "Simpan template" }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body).toMatchObject({
      version: 0,
      accent_color: "#0F766E",
      tagline: "Andal",
      rab_terms: null,
      spk_terms: "Pekerjaan dimulai setelah uang muka diterima.",
      bast_terms: null,
      payment_account_number: null,
      show_item_codes: true,
    });
  });

  it("is read-only without org.update", () => {
    renderAs(["documents.read"], <DocumentSettingsForm settings={settings} />);
    expect(screen.getByLabelText(/tagline/i)).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Simpan template" })).toBeNull();
    expect(screen.getByText(/Hanya Owner\/Admin/)).toBeInTheDocument();
  });
});

describe("RabImportPreview", () => {
  const job: ImportJob = {
    id: "j1",
    status: "previewed",
    filename: "item.csv",
    row_count: 2,
    valid_count: 1,
    error_count: 1,
    warnings: [],
    rows: [
      {
        row: 2,
        valid: true,
        errors: [],
        action: "add_item",
        data: { name: "Semen", quantity: "10", unit: "sak", unit_price: "65000", subtotal: "650000.00", item_type: "material", code: null, category: "Material" },
      },
      { row: 3, valid: false, errors: ["Volume: harus lebih dari 0."], action: null, data: { name: "Nol", quantity: null, unit: "m" } },
    ],
    result: null,
    created_at: "2026-10-19T00:00:00Z",
    committed_at: null,
  };

  it("shows server-computed subtotals and skipped rows; commits only valid rows", async () => {
    const onCommit = vi.fn();
    render(<RabImportPreview job={job} busy={null} backHref="/rab/r1?v=1" onCommit={onCommit} onDiscard={vi.fn()} onRestart={vi.fn()} />);
    const semen = screen.getByText("Semen").closest("tr")!;
    expect(within(semen).getByText(/Rp\s650\.000/)).toBeInTheDocument();
    expect(within(semen).getByText("Material · Material/barang")).toBeInTheDocument();
    expect(within(screen.getByText("Nol").closest("tr")!).getByText("Dilewati")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Tambahkan 1 item" }));
    expect(onCommit).toHaveBeenCalled();
  });

  it("reports the result with a way back to the RAB", () => {
    render(
      <RabImportPreview
        job={{ ...job, status: "committed", result: { items_created: 1 } }}
        busy={null}
        backHref="/rab/r1?v=1"
        onCommit={vi.fn()}
        onDiscard={vi.fn()}
        onRestart={vi.fn()}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("1 item ditambahkan.");
    expect(screen.getByRole("link", { name: "Kembali ke RAB" })).toHaveAttribute("href", "/rab/r1?v=1");
  });
});

describe("formatBytes", () => {
  it("formats sizes for display", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(65_843)).toBe("64,3 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3 MB");
  });
});
