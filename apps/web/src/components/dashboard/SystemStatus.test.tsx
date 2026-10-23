import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithQuery } from "@/test/render";
import { SystemStatus } from "./SystemStatus";

const healthy = {
  status: "ok",
  version: "0.1.0",
  environment: "development",
  time: "2026-10-18T20:00:00+07:00",
  database: "ok",
  ai: "disabled",
};

function respond(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("SystemStatus", () => {
  it("shows a loading state, then component statuses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(200, healthy)));
    renderWithQuery(<SystemStatus />);

    expect(screen.getByRole("status")).toHaveTextContent("Memeriksa status");
    expect(await screen.findByText("Normal")).toBeInTheDocument();
    expect(screen.getByText("Terhubung")).toBeInTheDocument();
    expect(screen.getByText("Belum dikonfigurasi")).toBeInTheDocument();
  });

  it("reports a degraded API when the database is down", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(respond(503, { ...healthy, status: "degraded", database: "error" })),
    );
    renderWithQuery(<SystemStatus />);

    expect(await screen.findByText("Terganggu")).toBeInTheDocument();
    expect(screen.getByText("Gagal")).toBeInTheDocument();
  });

  it("shows an error state and recovers on retry", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(respond(200, healthy));
    vi.stubGlobal("fetch", fetchMock);
    renderWithQuery(<SystemStatus />);

    expect(await screen.findByRole("alert")).toHaveTextContent("API tidak dapat dihubungi");

    await userEvent.click(screen.getByRole("button", { name: /periksa ulang/i }));
    expect(await screen.findByText("Normal")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
