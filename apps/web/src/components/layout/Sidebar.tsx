"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV_ITEMS, isActive } from "@/lib/navigation";

type SidebarProps = {
  onNavigate?: () => void;
};

export function Sidebar({ onNavigate }: SidebarProps) {
  const pathname = usePathname();

  return (
    <nav aria-label="Navigasi utama" className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
      <div className="flex h-14 items-center gap-2.5 border-b border-sidebar-border px-4">
        <span
          aria-hidden
          className="grid size-8 place-items-center rounded-md bg-sidebar-active text-sm font-bold text-sidebar-active-foreground"
        >
          R
        </span>
        <span className="text-[15px] font-bold tracking-tight">
          RABmate <span className="font-medium text-sidebar-muted">AI</span>
        </span>
      </div>
      <ul className="flex-1 space-y-0.5 overflow-y-auto p-2">
        {NAV_ITEMS.map((item) => {
          const active = isActive(item, pathname);
          const Icon = item.icon;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={[
                  "flex min-h-11 items-center gap-3 rounded-md px-3 text-sm transition-colors focus-visible:outline-sidebar-foreground lg:min-h-9",
                  active
                    ? "bg-sidebar-active font-semibold text-sidebar-active-foreground"
                    : "text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-foreground",
                ].join(" ")}
              >
                <Icon aria-hidden className="size-4 shrink-0" />
                <span className="flex-1 truncate">{item.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
