/** Underline tabs used by every tablist. Scrolls sideways instead of wrapping on narrow screens. */
export const TAB_LIST = "flex gap-1 overflow-x-auto overflow-y-hidden border-b border-border";

/** One tab button: 44px tall on phones, the selected one underlined in ink. */
export function tabClass(selected: boolean, size: "md" | "sm" = "md"): string {
  const sizing = size === "sm" ? "px-2 text-xs sm:min-h-9" : "px-3 text-sm sm:min-h-10";
  const state = selected
    ? "border-primary font-semibold text-foreground"
    : "border-transparent font-medium text-muted hover:text-foreground";
  return `-mb-px inline-flex min-h-11 shrink-0 items-center whitespace-nowrap border-b-2 transition-colors focus-visible:-outline-offset-2 ${sizing} ${state}`;
}
