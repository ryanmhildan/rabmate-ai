import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderAs } from "@/test/render";
import { THEME_KEY } from "@/lib/theme";
import { UserMenu } from "./UserMenu";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

afterEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("UserMenu theme options", () => {
  it("shows the saved choice as checked and switches theme on click", async () => {
    window.localStorage.setItem(THEME_KEY, "light");
    renderAs([], <UserMenu />);

    await userEvent.click(screen.getByRole("button", { name: /Estimator Uji/ }));
    const group = screen.getByRole("group", { name: "Tema tampilan" });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("menuitemradio", { name: "Terang" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("menuitemradio", { name: "Gelap" })).toHaveAttribute("aria-checked", "false");

    await userEvent.click(screen.getByRole("menuitemradio", { name: "Gelap" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("menuitemradio", { name: "Gelap" })).toHaveAttribute("aria-checked", "true");

    await userEvent.click(screen.getByRole("menuitemradio", { name: "Ikuti sistem" }));
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(window.localStorage.getItem(THEME_KEY)).toBeNull();
  });

  it("closes on Escape", async () => {
    renderAs([], <UserMenu />);
    await userEvent.click(screen.getByRole("button", { name: /Estimator Uji/ }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
