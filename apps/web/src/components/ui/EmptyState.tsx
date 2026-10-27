import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

type EmptyStateProps = {
  icon: LucideIcon;
  title: string;
  description: ReactNode;
  children?: ReactNode;
};

export function EmptyState({ icon: Icon, title, description, children }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center rounded-lg border border-dashed border-border bg-surface px-6 py-12 text-center">
      <span className="mb-4 grid size-12 place-items-center rounded-lg bg-primary-soft text-primary">
        <Icon aria-hidden className="size-6" />
      </span>
      <h2 className="text-base font-semibold">{title}</h2>
      <div className="mt-1 max-w-md text-sm text-muted">{description}</div>
      {children && <div className="mt-4">{children}</div>}
    </div>
  );
}
