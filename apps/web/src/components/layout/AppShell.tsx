"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Menu, X } from "lucide-react";
import { Breadcrumb } from "./Breadcrumb";
import { Sidebar } from "./Sidebar";
import { UserMenu } from "./UserMenu";

export function AppShell({ children }: { children: ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 border-r border-sidebar-border bg-sidebar lg:block">
        <Sidebar />
      </aside>

      {/* Mobile / tablet drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button
            type="button"
            aria-label="Tutup menu"
            className="absolute inset-0 bg-black/40"
            onClick={() => setDrawerOpen(false)}
          />
          <aside className="relative h-full w-72 max-w-[85vw] bg-sidebar shadow-xl">
            <button
              type="button"
              aria-label="Tutup menu"
              className="absolute top-1.5 right-2 grid size-11 place-items-center rounded-md text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-foreground focus-visible:outline-sidebar-foreground"
              onClick={() => setDrawerOpen(false)}
            >
              <X className="size-5" />
            </button>
            <Sidebar onNavigate={() => setDrawerOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-surface px-4 sm:px-6">
          <button
            type="button"
            aria-expanded={drawerOpen}
            className="-ml-2 inline-flex min-h-11 items-center gap-2 rounded-md px-2 text-sm font-medium hover:bg-surface-muted lg:hidden"
            onClick={() => setDrawerOpen(true)}
          >
            <Menu aria-hidden className="size-5" />
            Menu
          </button>
          <Breadcrumb />
          <UserMenu />
        </header>
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}
