"use client";

import { Check, ChevronDown, LogOut, Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useLogout, useMe } from "@/lib/auth";
import { THEME_CHOICES, applyTheme, readTheme, type ThemeChoice } from "@/lib/theme";

const THEME_ICONS = { system: Monitor, light: Sun, dark: Moon } as const;

export function UserMenu() {
  const me = useMe();
  const logout = useLogout();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  // Read lazily on open: localStorage does not exist during server rendering.
  const [theme, setTheme] = useState<ThemeChoice | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const initials = me.user.full_name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
  const current = theme ?? "system";

  return (
    <div ref={ref} className="relative ml-auto">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => {
          if (!open) setTheme(readTheme());
          setOpen((value) => !value);
        }}
        className="flex min-h-11 items-center gap-2 rounded-md px-1.5 text-left hover:bg-surface-muted lg:min-h-10"
      >
        <span
          aria-hidden
          className="grid size-8 place-items-center rounded-full bg-primary-soft text-xs font-semibold text-primary"
        >
          {initials}
        </span>
        <span className="hidden min-w-0 sm:block">
          <span className="block max-w-[180px] truncate text-sm font-medium">{me.user.full_name}</span>
          <span className="block max-w-[180px] truncate text-xs text-muted">
            {me.organization.name}
          </span>
        </span>
        <ChevronDown aria-hidden className="size-4 text-muted" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-40 mt-1 w-64 rounded-lg border border-border bg-surface py-1 shadow-lg"
        >
          <div className="border-b border-border px-3 py-2">
            <p className="truncate text-sm font-medium">{me.user.full_name}</p>
            <p className="truncate text-xs text-muted">{me.user.email}</p>
            <p className="mt-1 truncate text-xs text-muted">
              {me.organization.name} · {me.role_label}
            </p>
          </div>
          <div role="group" aria-label="Tema tampilan" className="border-b border-border py-1">
            <p className="px-3 pt-1 pb-0.5 text-xs font-medium text-muted">Tema</p>
            {THEME_CHOICES.map(({ value, label }) => {
              const Icon = THEME_ICONS[value];
              return (
                <button
                  key={value}
                  type="button"
                  role="menuitemradio"
                  aria-checked={current === value}
                  onClick={() => {
                    applyTheme(value);
                    setTheme(value);
                  }}
                  className="flex min-h-11 w-full items-center gap-2 px-3 text-sm hover:bg-surface-muted focus-visible:-outline-offset-2 sm:min-h-10"
                >
                  <Icon aria-hidden className="size-4 text-muted" />
                  <span className="flex-1 text-left">{label}</span>
                  {current === value && <Check aria-hidden className="size-4 text-primary" />}
                </button>
              );
            })}
          </div>
          <button
            type="button"
            role="menuitem"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              await logout();
            }}
            className="flex min-h-11 w-full items-center gap-2 px-3 text-sm hover:bg-surface-muted focus-visible:-outline-offset-2 disabled:opacity-50 sm:min-h-10"
          >
            <LogOut aria-hidden className="size-4" />
            Keluar
          </button>
        </div>
      )}
    </div>
  );
}
