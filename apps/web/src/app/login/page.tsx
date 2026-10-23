import type { Metadata } from "next";
import { Suspense } from "react";
import { LoginForm } from "@/components/auth/LoginForm";

export const metadata: Metadata = { title: "Masuk" };

export default function LoginPage() {
  return (
    <main className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2">
          <span
            aria-hidden
            className="grid size-9 place-items-center rounded-md bg-primary font-bold text-primary-foreground"
          >
            R
          </span>
          <span className="text-lg font-semibold tracking-tight">RABmate AI</span>
        </div>
        <div className="rounded-lg border border-border bg-surface p-6 shadow-sm">
          <h1 className="text-lg font-semibold">Masuk</h1>
          <p className="mt-1 mb-5 text-sm text-muted">Gunakan akun yang diberikan admin organisasi.</p>
          {/* useSearchParams needs a Suspense boundary under Cache Components. */}
          <Suspense>
            <LoginForm />
          </Suspense>
        </div>
      </div>
    </main>
  );
}
