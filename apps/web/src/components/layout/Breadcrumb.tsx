"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight } from "lucide-react";
import { findNavItem } from "@/lib/navigation";

export function Breadcrumb() {
  const pathname = usePathname();
  const current = findNavItem(pathname);

  return (
    <nav aria-label="Breadcrumb" className="min-w-0">
      <ol className="flex items-center gap-1 text-sm text-muted">
        <li>
          <Link href="/" className="inline-flex min-h-11 items-center hover:text-foreground">
            Beranda
          </Link>
        </li>
        {current && current.href !== "/" && (
          <>
            <li aria-hidden>
              <ChevronRight className="size-3.5" />
            </li>
            <li aria-current="page" className="truncate font-medium text-foreground">
              {current.label}
            </li>
          </>
        )}
      </ol>
    </nav>
  );
}
