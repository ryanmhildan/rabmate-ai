"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/Button";

export default function ErrorPage({ error, retry }: { error: unknown; retry: () => void }) {
  useEffect(() => {
    // Browser console only; server-side details never reach the client.
    console.error(error);
  }, [error]);

  return (
    <main className="grid min-h-screen place-items-center px-4">
      <div className="text-center" role="alert">
        <h1 className="text-2xl font-bold tracking-tight">Terjadi kesalahan</h1>
        <p className="mt-1 text-sm text-muted">
          Halaman gagal dimuat. Coba lagi; jika masalah berlanjut, hubungi administrator.
        </p>
        <Button className="mt-6" onClick={() => retry()}>
          Coba lagi
        </Button>
      </div>
    </main>
  );
}
