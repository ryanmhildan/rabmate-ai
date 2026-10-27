import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderAs } from "@/test/render";
import type { DashboardSummary } from "@/lib/types";
import { DashboardPage, actionsFrom } from "./DashboardPage";

const summary: DashboardSummary = {
  rab: { draft: 2, in_review: 1, approved: 3, approved_total: [{ currency: "IDR", total: "450000000.00", count: 3 }] },
  projects_total: 4,
  projects_by_status: { prospect: 1, active: 2, on_hold: 0, completed: 1, cancelled: 0 },
  clients_active: 3,
  open_budget: [{ currency: "IDR", total: "900000000.00", projects: 3 }],
  documents: { issued: 5, void: 1, approved_rab_not_issued: 0 },
  quotations: { draft: 0, in_review: 0, awaiting_response: 2, accepted: 1 },
  billing: {
    outstanding: [{ currency: "IDR", total: "125000000.00", count: 2 }],
    overdue: [{ currency: "IDR", total: "40000000.00", count: 1 }],
    received_this_month: [],
    terms_due_soon: 0,
  },
  workorders: { accepted_without_spk: 0, spk_in_review: 0, spk_open: 1, bast_in_review: 1 },
  recent_activity: [],
};

function respond(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

function serve(data: DashboardSummary) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(
        String(url).includes("/dashboard/summary")
          ? respond(data)
          : respond({ status: "ok", version: "0.1.0", environment: "test", time: "2026-10-23T09:00:00+07:00", database: "ok", ai: "disabled" }),
      ),
    ),
  );
}

describe("actionsFrom", () => {
  it("puts overdue invoices first and drops empty queues", () => {
    expect(actionsFrom(summary).map((a) => [a.label, a.count])).toEqual([
      ["Invoice lewat jatuh tempo", 1],
      ["RAB menunggu approval", 1],
      ["BAST menunggu review", 1],
      ["Penawaran menunggu tanggapan klien", 2],
    ]);
  });

  it("leaves out queues the role cannot see", () => {
    const limited = { ...summary, billing: null, rab: null, documents: null, quotations: null };
    expect(actionsFrom(limited).map((a) => a.label)).toEqual(["BAST menunggu review"]);
  });
});

describe("DashboardPage", () => {
  it("lists what needs action and marks outstanding invoices as the key figure", async () => {
    serve(summary);
    renderAs([], <DashboardPage />);

    const actions = await screen.findByRole("region", { name: "Perlu tindakan" });
    const links = await within(actions).findAllByRole("link");
    expect(links[0]).toHaveTextContent("Invoice lewat jatuh tempo");
    expect(links[0]).toHaveAttribute("href", "/invoice?overdue=true");

    const money = screen.getByRole("region", { name: "Keuangan" });
    const mark = money.querySelector("mark");
    expect(mark).toHaveTextContent(/125\.000\.000/);
    // Only one stabilo figure on the screen.
    expect(document.querySelectorAll("mark")).toHaveLength(1);
  });

  it("says so when nothing is waiting", async () => {
    serve({
      ...summary,
      rab: { ...summary.rab!, in_review: 0 },
      quotations: { ...summary.quotations!, awaiting_response: 0 },
      billing: { ...summary.billing!, overdue: [] },
      workorders: { ...summary.workorders, bast_in_review: 0 },
    });
    renderAs([], <DashboardPage />);

    expect(await screen.findByText("Tidak ada antrean yang menunggu Anda.")).toBeInTheDocument();
  });
});
