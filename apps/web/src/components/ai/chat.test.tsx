import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { AiStatus, ChatSource, Conversation } from "@/lib/types";
import { renderAs } from "@/test/render";
import { ProjectChat, questionError, sourceHref, withCitations } from "./ProjectChat";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const ready: AiStatus = {
  enabled: true,
  state: "ready",
  message: "Siap.",
  model: "rabmate",
  toolsets: [],
  ocr: { available: false, message: "OCR tidak tersedia." },
  upload_max_mb: 10,
  accepted_files: ".pdf",
};

const rabSource: ChatSource = {
  id: "S2",
  kind: "rab",
  label: "RAB-2026-0002 v1 (draft) · Jaringan",
  ref: { type: "rab", id: "rab1" },
  data: { grand_total: "Rp 10.946.265" },
};

function conversation(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: "c1",
    project_id: "p1",
    title: "Berapa total RAB?",
    created_at: "2026-10-20T06:00:00Z",
    updated_at: "2026-10-20T06:00:05Z",
    messages: [
      {
        id: "m1",
        role: "user",
        content: "Berapa total RAB?",
        sources: [],
        warnings: [],
        assumptions: [],
        questions: [],
        created_at: "2026-10-20T06:00:00Z",
      },
      {
        id: "m2",
        role: "assistant",
        content: "Total RAB Rp 10.946.265 [S2]. Belum termasuk ongkir.",
        sources: [rabSource, { ...rabSource, id: "S1", label: "Proyek PRJ-2026-0005", ref: null, cited: false }],
        warnings: ["Angka 1.000 tidak ditemukan di data sumber (bisa hasil hitungan atau karangan AI). Periksa sebelum dipakai."],
        assumptions: ["Harga sudah termasuk PPN."],
        questions: ["Apakah ongkos kirim ditanggung klien?"],
        created_at: "2026-10-20T06:00:05Z",
      },
    ],
    latest_run: {
      id: "run1",
      status: "succeeded",
      error_code: null,
      error_message: null,
      model: "rabmate",
      duration_ms: 4000,
      created_at: "2026-10-20T06:00:00Z",
      finished_at: "2026-10-20T06:00:05Z",
    },
    unavailable: ["Invoice dan pembayaran (Anda tidak memiliki izin keuangan)."],
    ...overrides,
  };
}

describe("chat helpers", () => {
  it("validates questions and links sources to their pages", () => {
    expect(questionError(" ")).toMatch(/Tulis pertanyaan/);
    expect(questionError("x".repeat(2001))).toMatch(/maksimal 2000/);
    expect(questionError("Total?")).toBeNull();
    expect(sourceHref(rabSource)).toBe("/rab/rab1");
    expect(sourceHref({ ...rabSource, ref: { type: "catalog_item", id: "k1" } })).toBe("/katalog-harga/k1");
    expect(sourceHref({ ...rabSource, ref: { type: "project_documents", id: "p1" } })).toBeNull();
    expect(sourceHref({ ...rabSource, ref: null })).toBeNull();
  });

  it("shows citations as markers without interpreting the answer as HTML", () => {
    render(<p data-testid="answer">{withCitations("Total <b>Rp 5</b> [S1, S2] dan [S3].")}</p>);
    const answer = screen.getByTestId("answer");
    expect(answer.querySelectorAll("sup")).toHaveLength(2);
    expect(answer.querySelector("b")).toBeNull();
    expect(answer.textContent).toBe("Total <b>Rp 5</b> S1, S2 dan S3.");
  });
});

describe("ProjectChat", () => {
  it("asks a question and shows the answer with its sources, checks and gaps", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/ai/status")) return Promise.resolve(json(200, ready));
      if (url.endsWith("/projects/p1/ai-conversations") && init?.method === "POST")
        return Promise.resolve(json(202, conversation()));
      if (url.endsWith("/projects/p1/ai-conversations")) return Promise.resolve(json(200, []));
      return Promise.resolve(json(200, conversation()));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderAs(["ai.use", "projects.read"], <ProjectChat projectId="p1" />);
    const user = userEvent.setup();
    const send = await screen.findByRole("button", { name: /kirim/i });
    await user.click(send);
    expect(screen.getByText("Tulis pertanyaan Anda.")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Pertanyaan untuk asisten"), "Berapa total RAB?");
    await user.click(send);
    expect(await screen.findByText(/Belum termasuk ongkir/)).toBeInTheDocument();
    const [, init] = fetchMock.mock.calls.find(([u, i]) => u.endsWith("/ai-conversations") && i?.method === "POST")!;
    expect(JSON.parse(init!.body as string)).toEqual({ message: "Berapa total RAB?" });
    expect(screen.getByText(/tidak ditemukan di data sumber/)).toBeInTheDocument();
    expect(screen.getByText("Harga sudah termasuk PPN.")).toBeInTheDocument();
    expect(screen.getByText("Apakah ongkos kirim ditanggung klien?")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /RAB-2026-0002 v1/ })).toHaveAttribute("href", "/rab/rab1");
    expect(screen.getByText(/Tidak termasuk dalam data jawaban terakhir/)).toBeInTheDocument();
    expect(screen.getByText("(terkait, tidak dikutip AI)")).toBeInTheDocument();
  });

  it("shows progress while answering and the error when it fails", async () => {
    const running = conversation({
      messages: conversation().messages.slice(0, 1),
      latest_run: { ...conversation().latest_run!, status: "running" },
    });
    const failed = conversation({
      messages: conversation().messages.slice(0, 1),
      latest_run: { ...conversation().latest_run!, status: "failed", error_message: "Hermes tidak dapat dihubungi." },
    });
    let detail = running;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith("/ai/status")) return Promise.resolve(json(200, ready));
        if (url.endsWith("/projects/p1/ai-conversations") && init?.method === "POST") return Promise.resolve(json(202, running));
        if (url.endsWith("/projects/p1/ai-conversations")) return Promise.resolve(json(200, []));
        return Promise.resolve(json(200, detail));
      }),
    );
    renderAs(["ai.use", "projects.read"], <ProjectChat projectId="p1" />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Pertanyaan untuk asisten"), "Berapa total RAB?");
    await user.click(screen.getByRole("button", { name: /kirim/i }));
    expect(await screen.findByText(/sedang menyusun jawaban/)).toBeInTheDocument();
    expect(screen.getByLabelText("Pertanyaan untuk asisten")).toBeDisabled();

    detail = failed;
    expect(await screen.findByText(/Hermes tidak dapat dihubungi/, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByLabelText("Pertanyaan untuk asisten")).toBeEnabled();
  });
});
