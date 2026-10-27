import { ChevronRight } from "lucide-react";
import type { Metadata } from "next";
import { Suspense } from "react";
import { LoginForm } from "@/components/auth/LoginForm";

export const metadata: Metadata = { title: "Masuk" };

const DOCUMENT_FLOW = ["RAB", "Penawaran", "SPK", "BAST", "Invoice"];

export default function LoginPage() {
  return (
    <main className="grid min-h-screen lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      {/* Ink cover, same as the sidebar. Hidden on small screens where the form needs the room. */}
      <section
        aria-label="Tentang RABmate AI"
        className="hidden flex-col justify-between bg-sidebar p-10 text-sidebar-foreground lg:flex"
      >
        <Brand />
        <div>
          <p className="max-w-sm text-3xl leading-tight font-bold tracking-tight">
            Susun RAB, kirim penawaran, dan tagih proyek dari{" "}
            <mark className="rounded-sm bg-highlight px-1 text-highlight-foreground">satu tempat</mark>.
          </p>
          <ol aria-label="Alur dokumen" className="mt-6 flex flex-wrap items-center gap-1.5 text-sm text-sidebar-muted">
            {DOCUMENT_FLOW.map((step, index) => (
              <li key={step} className="flex items-center gap-1.5">
                {index > 0 && <ChevronRight aria-hidden className="size-3.5" />}
                {step}
              </li>
            ))}
          </ol>
        </div>
        <p className="text-xs text-sidebar-muted">AI berjalan di server Anda sendiri. Harga tetap Anda verifikasi.</p>
      </section>

      <div className="grid place-items-center px-4 py-10">
        <div className="w-full max-w-sm">
          <div className="mb-6 lg:hidden">
            <Brand />
          </div>
          <div className="rounded-lg border border-border bg-surface p-6">
            <h1 className="text-xl font-bold tracking-tight">Masuk</h1>
            <p className="mt-1 mb-5 text-sm text-muted">Gunakan akun yang diberikan admin organisasi.</p>
            {/* useSearchParams needs a Suspense boundary under Cache Components. */}
            <Suspense>
              <LoginForm />
            </Suspense>
          </div>
        </div>
      </div>
    </main>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <span
        aria-hidden
        className="grid size-9 place-items-center rounded-md bg-primary font-bold text-primary-foreground lg:bg-sidebar-active lg:text-sidebar-active-foreground"
      >
        R
      </span>
      <span className="text-lg font-bold tracking-tight">
        RABmate <span className="font-medium text-muted lg:text-sidebar-muted">AI</span>
      </span>
    </div>
  );
}
