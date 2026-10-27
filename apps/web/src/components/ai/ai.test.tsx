import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { AiExtractItem, AiRun, AiStatus, RabVersion, SourceDocument } from "@/lib/types";
import { renderAs } from "@/test/render";
import { AiAssistantCard, aiRequestError } from "./AiAssistantCard";
import { AiReviewDialog, applyPayload, rowProblem, rowsFromRun, sourceLocation, type ReviewRow } from "./AiReviewDialog";
import { uploadProblem } from "./SourceDocumentPicker";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const version = { version_no: 1, editable: true, currency: "IDR" } as RabVersion;
const ready: AiStatus = {
  enabled: true,
  state: "ready",
  message: "Siap.",
  model: "rabmate",
  toolsets: [],
  ocr: { available: false, message: "OCR tidak tersedia: Tesseract belum terpasang." },
  upload_max_mb: 10,
  accepted_files: ".pdf, .xlsx, .csv, .txt, .png, .jpg, .jpeg",
};

function run(overrides: Partial<AiRun> = {}): AiRun {
  return {
    id: "run1",
    kind: "extract_items",
    status: "succeeded",
    created_by: { id: "u1", email: "e@x.test", full_name: "Eko Estimator" },
    created_at: "2026-10-19T06:00:00Z",
    finished_at: "2026-10-19T06:00:20Z",
    item_count: 2,
    applied_count: null,
    error_message: null,
    rab_version_id: "v1",
    source_document_id: null,
    input: { text: "1 | Kabel | 305 | m | 4.300", source_label: "penawaran.pdf", number_format: "id" },
    context: { rab: { number: "RAB-1", title: "RAB", version_no: 1, item_count: 0, items: [] } },
    result: {
      items: [
        {
          name: "Kabel UTP",
          specification: null,
          quantity: "305",
          unit: "m",
          unit_price: "4300",
          total: null,
          source_line: 1,
          source_excerpt: "1 | Kabel | 305 | m | 4.300",
          unknown_fields: ["jumlah"],
          warnings: [],
        },
        {
          name: "Patch panel",
          specification: null,
          quantity: null,
          unit: "unit",
          unit_price: null,
          total: null,
          source_line: null,
          source_excerpt: null,
          unknown_fields: ["volume"],
          warnings: ["Volume '2x' tidak sesuai format angka Indonesia (1.234.567,89); dikosongkan."],
        },
      ],
      notes: [],
      warnings: [],
    },
    error_code: null,
    model: "rabmate",
    attempts: 1,
    duration_ms: 20000,
    started_at: "2026-10-19T06:00:00Z",
    applied_at: null,
    can_apply: true,
    can_discard: true,
    ...overrides,
  };
}

describe("AI request form rules", () => {
  it("validates description and document text before sending", () => {
    expect(aiRequestError("rab_draft", "pendek", "")).toMatch(/minimal 10/);
    expect(aiRequestError("rab_draft", "Instalasi jaringan 48 titik", "")).toBeNull();
    expect(aiRequestError("extract_items", "", "   ")).toMatch(/minimal 10/);
    expect(aiRequestError("extract_items", "", "x".repeat(20_001))).toMatch(/maksimal/);
    expect(aiRequestError("extract_document", "", "", null)).toMatch(/pilih dokumen/);
    expect(aiRequestError("extract_document", "", "", "doc1")).toBeNull();
  });

  it("checks files before uploading them", () => {
    const file = (name: string, size: number) => new File([new Uint8Array(size)], name);
    expect(uploadProblem(file("penawaran.PDF", 10), ready)).toBeNull();
    expect(uploadProblem(file("kosong.pdf", 0), ready)).toMatch(/kosong/);
    expect(uploadProblem(file("besar.pdf", 10 * 1024 * 1024 + 1), ready)).toMatch(/melebihi 10 MB/);
    expect(uploadProblem(file("dokumen.docx", 10), ready)).toMatch(/Format tidak didukung/);
  });

  it("locates file rows by page and pasted rows by line", () => {
    const item = (run().result!.items[0] as AiExtractItem);
    expect(sourceLocation(item)).toBe("Baris 1");
    expect(sourceLocation({ ...item, source_page: "Halaman 2", source_page_line: 5 })).toBe("Halaman 2, baris 5");
    expect(sourceLocation({ ...item, source_page: "Sheet RAB", source_page_line: null })).toBe("Sheet RAB");
  });
});

describe("AI review rows", () => {
  it("starts unsized lines unticked and keeps document prices as an explicit choice", () => {
    const rows = rowsFromRun(run());
    expect(rows.map((r) => [r.include, r.price, r.documentPrice])).toEqual([
      [true, "document", "4300"],
      [false, "none", null],
    ]);
  });

  it("explains what the server would refuse and sends only ticked rows", () => {
    const [kabel, panel] = rowsFromRun(run());
    const base: ReviewRow = { ...panel, include: true };
    expect(rowProblem(base)).toMatch(/Volume wajib/);
    expect(rowProblem({ ...base, quantity: "1.000.000" })).toMatch(/Volume wajib/);
    expect(rowProblem({ ...base, quantity: "2", price: "catalog" })).toMatch(/Pilih harga katalog/);
    expect(rowProblem({ ...base, quantity: "2", price: "document" })).toMatch(/tidak mencantumkan harga/);
    expect(rowProblem({ ...kabel, unit: "roll" })).toMatch(/satuan m/);
    expect(rowProblem({ ...base, quantity: "2" })).toBeNull();

    expect(
      applyPayload([
        kabel,
        { ...panel, include: true, quantity: "2", price: "catalog", observation: { id: "obs1", price: "1750000", label: "Patch panel" } },
        { ...panel, index: 5, include: false },
      ]),
    ).toEqual({
      items: [
        { index: 0, name: "Kabel UTP", quantity: "305", unit: "m", item_type: "material", price: "document", price_observation_id: null },
        { index: 1, name: "Patch panel", quantity: "2", unit: "unit", item_type: "material", price: "catalog", price_observation_id: "obs1" },
      ],
    });
  });
});

describe("AiAssistantCard", () => {
  it("shows why AI is unavailable and offers no request form", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(
          url.endsWith("/ai/status")
            ? json(200, { ...ready, enabled: false, state: "disabled", message: "Asisten AI lokal belum diaktifkan (AI_ENABLED=false)." })
            : json(200, []),
        ),
      ),
    );
    renderAs(["ai.use", "rab.write", "rab.read"], <AiAssistantCard rabId="r1" projectId="p1" version={version} onApplied={vi.fn()} />);
    expect(await screen.findByText("Belum diaktifkan")).toBeInTheDocument();
    expect(screen.getByText(/AI_ENABLED=false/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /minta draft/i })).toBeNull();
  });

  it("validates, then sends the request for the selected version", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/ai/status")) return Promise.resolve(json(200, ready));
      if (init?.method === "POST") return Promise.resolve(json(202, run({ status: "queued", result: null })));
      return Promise.resolve(json(200, []));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderAs(["ai.use", "rab.write", "rab.read"], <AiAssistantCard rabId="r1" projectId="p1" version={version} onApplied={vi.fn()} />);
    const user = userEvent.setup();
    const button = await screen.findByRole("button", { name: /minta draft/i });
    await user.type(screen.getByLabelText(/deskripsi pekerjaan/i), "pendek");
    await user.click(button);
    expect(screen.getByText(/minimal 10 karakter/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);

    await user.type(screen.getByLabelText(/deskripsi pekerjaan/i), " instalasi jaringan 48 titik");
    await user.click(button);
    await vi.waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true));
    const [url, init] = fetchMock.mock.calls.find(([, i]) => i?.method === "POST")!;
    expect(url).toBe("/api/v1/rab/r1/versions/1/ai-runs");
    expect(JSON.parse(init!.body as string)).toEqual({ kind: "rab_draft", description: "pendek instalasi jaringan 48 titik" });
  });
});

describe("AiAssistantCard: dari berkas", () => {
  it("uploads a file, selects it and asks for an extraction from it", async () => {
    const saved: SourceDocument & { duplicate: boolean } = {
      id: "doc1",
      project_id: "p1",
      filename: "penawaran.pdf",
      content_type: "application/pdf",
      kind: "pdf",
      size_bytes: 2048,
      sha256: "a".repeat(64),
      uploaded_by: { id: "u1", email: "e@x.test", full_name: "Eko Estimator" },
      created_at: "2026-10-20T06:00:00Z",
      duplicate: false,
    };
    let uploaded = false;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/ai/status")) return Promise.resolve(json(200, ready));
      if (url.endsWith("/projects/p1/source-documents")) {
        if (init?.method === "POST") {
          uploaded = true;
          return Promise.resolve(json(201, saved));
        }
        return Promise.resolve(json(200, uploaded ? [saved] : []));
      }
      if (init?.method === "POST") return Promise.resolve(json(202, run({ status: "queued", result: null })));
      return Promise.resolve(json(200, []));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderAs(["ai.use", "rab.write", "rab.read"], <AiAssistantCard rabId="r1" projectId="p1" version={version} onApplied={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Ekstraksi dari berkas" }));
    expect(screen.getByText(/Tesseract belum terpasang/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /minta draft/i }));
    expect(screen.getByText(/Unggah atau pilih dokumen sumber/)).toBeInTheDocument();

    await user.upload(screen.getByLabelText(/unggah berkas/i), new File(["%PDF-1.4"], "penawaran.pdf", { type: "application/pdf" }));
    await vi.waitFor(() => expect(screen.getByLabelText(/dokumen sumber proyek/i)).toHaveValue("doc1"));
    const [, uploadInit] = fetchMock.mock.calls.find(([u, i]) => u.endsWith("/source-documents") && i?.method === "POST")!;
    expect(uploadInit!.body).toBeInstanceOf(FormData);
    expect(screen.getByRole("link", { name: /unduh asli/i })).toHaveAttribute("href", "/api/v1/source-documents/doc1/file");

    await user.click(screen.getByRole("button", { name: /minta draft/i }));
    await vi.waitFor(() =>
      expect(fetchMock.mock.calls.some(([u, i]) => u.endsWith("/ai-runs") && i?.method === "POST")).toBe(true),
    );
    const [, init] = fetchMock.mock.calls.find(([u, i]) => u.endsWith("/ai-runs") && i?.method === "POST")!;
    expect(JSON.parse(init!.body as string)).toEqual({ kind: "extract_document", source_document_id: "doc1", number_format: "id" });
  });
});

describe("AiReviewDialog", () => {
  it("applies only reviewed, complete lines", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) =>
      Promise.resolve(init?.method === "POST" ? json(200, run({ status: "applied" })) : json(200, run())),
    );
    vi.stubGlobal("fetch", fetchMock);
    const onApplied = vi.fn();
    renderAs(
      ["ai.use", "rab.write", "rab.read"],
      <AiReviewDialog runId="run1" currency="IDR" onClose={vi.fn()} onChanged={vi.fn()} onApplied={onApplied} />,
    );
    const user = userEvent.setup();
    expect(await screen.findByText(/tidak sesuai format angka/)).toBeInTheDocument();
    expect(screen.getByText("Baris 1: 1 | Kabel | 305 | m | 4.300")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Pilih baris 2"));
    const apply = screen.getByRole("button", { name: /tambahkan 2 item/i });
    expect(apply).toBeDisabled(); // patch panel has no volume yet
    await user.type(screen.getByLabelText("Volume baris 2"), "2");
    expect(apply).toBeEnabled();
    await user.click(apply);

    await vi.waitFor(() => expect(onApplied).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls.find(([, i]) => i?.method === "POST")!;
    expect(url).toBe("/api/v1/ai-runs/run1/apply");
    expect(JSON.parse(init!.body as string).items.map((i: { index: number; price: string }) => [i.index, i.price])).toEqual([
      [0, "document"],
      [1, "none"],
    ]);
  });
});
