import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { PdfPreviewButton, downloadUrlOf } from "./PdfPreview";

const pdf = vi.hoisted(() => ({
  fetchPdf: vi.fn<(url: string) => Promise<ArrayBuffer>>(),
  rendered: [] as number[],
}));

// A stand-in for pdf.js: jsdom has no canvas, and what matters here is the dialog around it.
vi.mock("@/lib/pdf", () => ({
  fetchPdf: (url: string) => pdf.fetchPdf(url),
  loadPdfJs: async () => ({
    VerbosityLevel: { ERRORS: 0 },
    getDocument: () => ({
      promise: Promise.resolve({
        numPages: 2,
        getPage: async (number: number) => ({
          getViewport: ({ scale }: { scale: number }) => ({ width: 595 * scale, height: 842 * scale }),
          render: () => {
            pdf.rendered.push(number);
            return { promise: Promise.resolve(), cancel: () => {} };
          },
        }),
      }),
      destroy: async () => {},
    }),
  }),
}));

// jsdom lays nothing out; give the viewer a width to fit pages to.
const clientWidth = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientWidth");
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => 800 });
});
afterAll(() => {
  if (clientWidth) Object.defineProperty(HTMLElement.prototype, "clientWidth", clientWidth);
});
beforeEach(() => {
  pdf.fetchPdf.mockReset();
  pdf.rendered.length = 0;
});

const URL = "/api/v1/rab/r1/versions/1/preview.pdf";

describe("PdfPreviewButton", () => {
  it("draws every page inside the app and offers a download", async () => {
    pdf.fetchPdf.mockResolvedValue(new ArrayBuffer(8));
    render(<PdfPreviewButton url={URL} title="Pratinjau RAB-2026-0004 versi 1" />);

    await userEvent.click(screen.getByRole("button", { name: "Pratinjau PDF" }));
    const dialog = screen.getByRole("dialog", { name: "Pratinjau RAB-2026-0004 versi 1" });

    expect(await within(dialog).findByRole("img", { name: "Halaman 1 dari 2" })).toBeInTheDocument();
    expect(within(dialog).getByRole("img", { name: "Halaman 2 dari 2" })).toBeInTheDocument();
    expect(within(dialog).getByText("2 halaman")).toBeInTheDocument();
    expect(pdf.fetchPdf).toHaveBeenCalledWith(URL);
    expect(pdf.rendered).toEqual(expect.arrayContaining([1, 2]));
    expect(within(dialog).getByRole("link", { name: "Unduh PDF" })).toHaveAttribute(
      "href",
      `${URL}?download=true`,
    );
  });

  it("zooms in steps and stops at the ends", async () => {
    pdf.fetchPdf.mockResolvedValue(new ArrayBuffer(8));
    render(<PdfPreviewButton url={URL} title="Pratinjau" />);
    await userEvent.click(screen.getByRole("button", { name: "Pratinjau PDF" }));
    await screen.findByRole("img", { name: "Halaman 1 dari 2" });

    await userEvent.click(screen.getByRole("button", { name: "Perbesar" }));
    expect(screen.getByText("125%")).toBeInTheDocument();
    for (let i = 0; i < 5; i++) await userEvent.click(screen.getByRole("button", { name: "Perbesar" }));
    expect(screen.getByText("200%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Perbesar" })).toBeDisabled();
  });

  it("shows the server's message and retries", async () => {
    pdf.fetchPdf.mockRejectedValueOnce(new Error("Versi RAB tidak ditemukan."));
    pdf.fetchPdf.mockResolvedValueOnce(new ArrayBuffer(8));
    render(<PdfPreviewButton url={URL} title="Pratinjau" />);
    await userEvent.click(screen.getByRole("button", { name: "Pratinjau PDF" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Versi RAB tidak ditemukan.");
    await userEvent.click(screen.getByRole("button", { name: "Coba lagi" }));
    expect(await screen.findByRole("img", { name: "Halaman 1 dari 2" })).toBeInTheDocument();
    expect(pdf.fetchPdf).toHaveBeenCalledTimes(2);
  });
});

describe("downloadUrlOf", () => {
  it("adds download=true to plain and query URLs", () => {
    expect(downloadUrlOf("/a.pdf")).toBe("/a.pdf?download=true");
    expect(downloadUrlOf("/a.pdf?x=1")).toBe("/a.pdf?x=1&download=true");
  });
});
