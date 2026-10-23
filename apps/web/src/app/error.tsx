"use client";

import { useEffect } from "react";

export default function ErrorPage({ error, retry }: { error: unknown; retry: () => void }) {
  useEffect(() => {
    // Browser console only; server-side details never reach the client.
    console.error(error);
  }, [error]);

  return (
    <main className="grid min-h-screen place-items-center px-4">
      <div className="text-center" role="alert">
        <h1 className="text-xl font-semibold">Terjadi kesalahan</h1>
        <p className="mt-1 text-sm text-muted">
          Halaman gagal dimuat. Coba lagi; jika masalah berlanjut, hubungi administrator.
        </p>
        <button
          type="button"
          onClick={() => retry()}
          className="mt-6 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
        >
          Coba lagi
        </button>
      </div>
    </main>
  );
}
