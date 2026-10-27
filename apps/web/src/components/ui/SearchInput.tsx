"use client";

import { Search } from "lucide-react";
import { useEffect, useEffectEvent, useState } from "react";

type SearchInputProps = {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  label?: string;
  delayMs?: number;
};

/** Debounced search box: local state while typing, `onChange` after a short pause. */
export function SearchInput({
  value,
  onChange,
  placeholder = "Cari…",
  label = "Cari",
  delayMs = 300,
}: SearchInputProps) {
  const [draft, setDraft] = useState(value);
  const emit = useEffectEvent((next: string) => onChange(next));

  useEffect(() => {
    if (draft === value) return;
    const timer = window.setTimeout(() => emit(draft.trim()), delayMs);
    return () => window.clearTimeout(timer);
  }, [draft, value, delayMs]);

  return (
    <div className="relative w-full sm:max-w-xs">
      <Search
        aria-hidden
        className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted"
      />
      <input
        type="search"
        aria-label={label}
        value={draft}
        placeholder={placeholder}
        maxLength={100}
        onChange={(event) => setDraft(event.target.value)}
        className="h-11 w-full rounded-md border border-border-control bg-surface pr-3 pl-8 text-base placeholder:text-muted focus:border-primary sm:h-9 sm:text-sm"
      />
    </div>
  );
}
