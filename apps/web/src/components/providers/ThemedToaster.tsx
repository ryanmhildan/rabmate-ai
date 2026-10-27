"use client";

import { useSyncExternalStore } from "react";
import { Toaster } from "sonner";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia(DARK_QUERY);
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  media.addEventListener("change", onChange);
  return () => {
    observer.disconnect();
    media.removeEventListener("change", onChange);
  };
}

function isDark(): boolean {
  const pinned = document.documentElement.dataset.theme;
  if (pinned === "dark" || pinned === "light") return pinned === "dark";
  return window.matchMedia(DARK_QUERY).matches;
}

/** Sonner keeps its own palette; this tells it which theme the page is in right now. */
export function ThemedToaster() {
  const dark = useSyncExternalStore(subscribe, isDark, () => false);
  return <Toaster position="top-right" richColors closeButton theme={dark ? "dark" : "light"} />;
}
