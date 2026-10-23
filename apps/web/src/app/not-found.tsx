import Link from "next/link";

export default function NotFound() {
  return (
    <main className="grid min-h-screen place-items-center px-4">
      <div className="text-center">
        <p className="text-sm font-medium text-primary">404</p>
        <h1 className="mt-2 text-xl font-semibold">Halaman tidak ditemukan</h1>
        <p className="mt-1 text-sm text-muted">Alamat yang Anda buka tidak tersedia.</p>
        <Link
          href="/"
          className="mt-6 inline-block rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
        >
          Kembali ke Dashboard
        </Link>
      </div>
    </main>
  );
}
