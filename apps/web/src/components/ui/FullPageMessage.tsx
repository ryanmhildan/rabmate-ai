import { Loader2 } from "lucide-react";
import { Button } from "./Button";

type FullPageMessageProps = {
  title: string;
  description?: string;
  loading?: boolean;
  action?: { label: string; onClick: () => void };
};

export function FullPageMessage({ title, description, loading, action }: FullPageMessageProps) {
  return (
    <main className="grid min-h-screen place-items-center px-4">
      <div className="text-center" role={loading ? "status" : "alert"} aria-live="polite">
        {loading && <Loader2 aria-hidden className="mx-auto mb-3 size-6 animate-spin text-muted" />}
        <h1 className="text-base font-semibold">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
        {action && (
          <Button className="mt-5" onClick={action.onClick}>
            {action.label}
          </Button>
        )}
      </div>
    </main>
  );
}
