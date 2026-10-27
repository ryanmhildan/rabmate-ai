import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderAs } from "@/test/render";
import type { Letterhead } from "@/lib/types";
import { LETTERHEAD_MAX_BYTES, LetterheadCard, letterheadProblem } from "./LetterheadCard";

const saved: Letterhead = {
  filename: "Kop PT Uji.png",
  content_type: "image/png",
  size_bytes: 48_213,
  sha256: "ab".repeat(32),
  width_px: 2400,
  height_px: 420,
  uploaded_at: "2026-10-25T03:00:00Z",
  uploaded_by: { id: "u1", email: "owner@example.test", full_name: "Owner Uji" },
};

function respond(status: number, body?: unknown) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Fake API: GET answers with `initial`, PUT stores `saved`, DELETE clears. */
function serve(initial: Letterhead | null) {
  const calls: string[] = [];
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push(`${method} ${url}`);
    if (method === "PUT") return Promise.resolve(respond(200, saved));
    if (method === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
    return Promise.resolve(respond(200, initial));
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

const png = (size = 1024) => new File([new Uint8Array(size)], "kop.png", { type: "image/png" });

describe("letterheadProblem", () => {
  it("checks size and type before uploading", () => {
    expect(letterheadProblem(png())).toBeNull();
    expect(letterheadProblem(png(0))).toBe("File kosong.");
    expect(letterheadProblem(png(LETTERHEAD_MAX_BYTES + 1))).toMatch(/2 MB/);
    expect(letterheadProblem(new File(["%PDF"], "kop.pdf", { type: "application/pdf" }))).toMatch(/PNG atau JPEG/);
  });
});

describe("LetterheadCard", () => {
  it("uploads a kop and shows it with its details", async () => {
    const calls = serve(null);
    renderAs(["org.update", "documents.read"], <LetterheadCard />);

    expect(await screen.findByText(/Belum ada kop surat/)).toBeInTheDocument();
    await userEvent.upload(screen.getByLabelText("Unggah kop"), png());

    const image = await screen.findByRole("img", { name: "Kop surat yang dipakai di PDF" });
    expect(image).toHaveAttribute("src", expect.stringContaining("/document-settings/letterhead/image?v="));
    expect(screen.getByText(/Kop PT Uji\.png · 2400 × 420 px/)).toBeInTheDocument();
    expect(screen.getByLabelText("Ganti kop")).toBeInTheDocument();
    expect(calls).toContain("PUT /api/v1/document-settings/letterhead");
  });

  it("refuses an oversized file without calling the server", async () => {
    const calls = serve(null);
    renderAs(["org.update", "documents.read"], <LetterheadCard />);
    await screen.findByText(/Belum ada kop surat/);

    await userEvent.upload(screen.getByLabelText("Unggah kop"), png(LETTERHEAD_MAX_BYTES + 1));
    expect(await screen.findByRole("alert")).toHaveTextContent("melebihi 2 MB");
    expect(calls.some((c) => c.startsWith("PUT"))).toBe(false);
  });

  it("deletes the kop after confirmation", async () => {
    const calls = serve(saved);
    renderAs(["org.update", "documents.read"], <LetterheadCard />);
    await screen.findByRole("img", { name: "Kop surat yang dipakai di PDF" });

    await userEvent.click(screen.getByRole("button", { name: "Hapus kop" }));
    const dialog = screen.getByRole("dialog", { name: "Hapus kop surat?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Hapus kop" }));

    await waitFor(() => expect(screen.getByText(/Belum ada kop surat/)).toBeInTheDocument());
    expect(calls).toContain("DELETE /api/v1/document-settings/letterhead");
  });

  it("is read-only without the organization permission", async () => {
    serve(saved);
    renderAs(["documents.read"], <LetterheadCard />);
    await screen.findByRole("img", { name: "Kop surat yang dipakai di PDF" });
    expect(screen.queryByLabelText(/Ganti kop|Unggah kop/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hapus kop" })).not.toBeInTheDocument();
    expect(screen.getByText(/Hanya Owner\/Admin/)).toBeInTheDocument();
  });
});
