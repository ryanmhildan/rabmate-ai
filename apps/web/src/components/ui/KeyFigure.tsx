/** Stabilo marker look. `box-decoration-clone` keeps the mark whole when a long figure wraps. */
export const HIGHLIGHT =
  "tabular box-decoration-clone rounded-sm bg-highlight px-1.5 py-0.5 font-bold text-highlight-foreground";

/**
 * The one figure a screen is about, marked with the stabilo highlight (DESIGN.md: at most one per
 * screen). Renders a <dt>/<dd> pair, so it goes inside a <dl>.
 */
export function KeyFigure({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-t border-border pt-2">
      <dt className="font-semibold">{label}</dt>
      <dd>
        <mark className={`${HIGHLIGHT} text-lg`}>{value}</mark>
      </dd>
    </div>
  );
}
