import Link from "next/link";
import { buttonClass } from "@/components/ui/Button";

export default function NotFound() {
  return (
    <main className="grid min-h-screen place-items-center px-4">
      <div className="text-center">
        <p className="text-sm font-medium text-primary">404</p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight">Halaman tidak ditemukan</h1>
        <p className="mt-1 text-sm text-muted">Alamat yang Anda buka tidak tersedia.</p>
        <Link href="/" className={buttonClass({ className: "mt-6" })}>
          Kembali ke Dashboard
        </Link>
      </div>
    </main>
  );
}
