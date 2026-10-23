import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Sidebar } from "./Sidebar";

const pathname = vi.hoisted(() => ({ current: "/" }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathname.current,
}));

describe("Sidebar", () => {
  it("renders every menu as a link", () => {
    render(<Sidebar />);

    expect(screen.getAllByRole("link")).toHaveLength(11);
    expect(screen.getByRole("link", { name: /katalog harga/i })).toHaveAttribute(
      "href",
      "/katalog-harga",
    );
  });

  it("marks only the current module as active", () => {
    pathname.current = "/rab/abc";
    render(<Sidebar />);

    const current = screen.getAllByRole("link").filter((link) => link.getAttribute("aria-current"));
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("RAB");
  });

  it("shows no phase label once every module is built", () => {
    pathname.current = "/";
    render(<Sidebar />);

    expect(screen.getByRole("link", { name: /dashboard/i })).not.toHaveTextContent(/fase/i);
    expect(screen.getByRole("link", { name: /^rab/i })).not.toHaveTextContent(/fase/i);
    expect(screen.getByRole("link", { name: /katalog harga/i })).not.toHaveTextContent(/fase/i);
    expect(screen.getByRole("link", { name: /^dokumen/i })).not.toHaveTextContent(/fase/i);
    expect(screen.getByRole("link", { name: /^penawaran/i })).not.toHaveTextContent(/fase/i);
    expect(screen.getByRole("link", { name: /^spk/i })).not.toHaveTextContent(/fase/i);
  });
});
