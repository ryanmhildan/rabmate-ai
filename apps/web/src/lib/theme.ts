/**
 * Light/dark choice. "system" follows the OS (no data-theme attribute); "light" and "dark" pin the
 * theme with <html data-theme>. The choice is a per-browser convenience kept in localStorage; it
 * is not account data and holds nothing sensitive.
 */
export type ThemeChoice = "system" | "light" | "dark";

export const THEME_KEY = "rabmate-theme";

export const THEME_CHOICES: { value: ThemeChoice; label: string }[] = [
  { value: "system", label: "Ikuti sistem" },
  { value: "light", label: "Terang" },
  { value: "dark", label: "Gelap" },
];

export function readTheme(): ThemeChoice {
  try {
    const saved = window.localStorage.getItem(THEME_KEY);
    return saved === "light" || saved === "dark" ? saved : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") delete root.dataset.theme;
  else root.dataset.theme = choice;
  try {
    if (choice === "system") window.localStorage.removeItem(THEME_KEY);
    else window.localStorage.setItem(THEME_KEY, choice);
  } catch {
    // Storage blocked (private mode): the choice still applies until the page reloads.
  }
}

/** Runs before the first paint so a pinned theme does not flash the other one. Static text only. */
export const THEME_BOOT_SCRIPT = `try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;
