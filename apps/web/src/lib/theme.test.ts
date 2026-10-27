import { afterEach, describe, expect, it, vi } from "vitest";
import { THEME_BOOT_SCRIPT, THEME_KEY, applyTheme, readTheme } from "./theme";

afterEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("theme choice", () => {
  it("follows the system when nothing is saved", () => {
    expect(readTheme()).toBe("system");
  });

  it("pins light or dark on <html> and remembers it", () => {
    applyTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem(THEME_KEY)).toBe("dark");
    expect(readTheme()).toBe("dark");

    applyTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(readTheme()).toBe("light");
  });

  it("going back to system clears both the attribute and the saved value", () => {
    applyTheme("dark");
    applyTheme("system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(window.localStorage.getItem(THEME_KEY)).toBeNull();
  });

  it("ignores values it did not write", () => {
    window.localStorage.setItem(THEME_KEY, "neon");
    expect(readTheme()).toBe("system");
  });

  it("still applies the theme when storage is blocked", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    applyTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("boot script restores a saved choice before React runs", () => {
    window.localStorage.setItem(THEME_KEY, "dark");
    new Function(THEME_BOOT_SCRIPT)();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
