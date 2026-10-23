import { describe, expect, it } from "vitest";
import { NAV_ITEMS, findNavItem } from "./navigation";

describe("navigation", () => {
  it("lists the eleven initial menus in order", () => {
    expect(NAV_ITEMS.map((item) => item.label)).toEqual([
      "Dashboard",
      "Proyek",
      "RAB",
      "Katalog Harga",
      "Klien",
      "Dokumen",
      "Penawaran",
      "Invoice & Pembayaran",
      "SPK & BAST",
      "Approval",
      "Pengaturan",
    ]);
  });

  it("has unique hrefs", () => {
    const hrefs = NAV_ITEMS.map((item) => item.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("matches nested paths to their module but not lookalike prefixes", () => {
    expect(findNavItem("/")?.label).toBe("Dashboard");
    expect(findNavItem("/rab/123")?.label).toBe("RAB");
    expect(findNavItem("/rabxyz")).toBeUndefined();
  });
});
