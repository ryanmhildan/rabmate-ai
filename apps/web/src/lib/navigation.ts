import {
  Building2,
  Calculator,
  ClipboardCheck,
  FileSignature,
  FileText,
  FolderKanban,
  Handshake,
  LayoutDashboard,
  type LucideIcon,
  Receipt,
  Settings,
  Tags,
} from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  description: string;
};

export const NAV_ITEMS: readonly NavItem[] = [
  {
    href: "/",
    label: "Dashboard",
    icon: LayoutDashboard,
    description: "Ringkasan proyek, biaya, dan dokumen.",
  },
  {
    href: "/proyek",
    label: "Proyek",
    icon: FolderKanban,
    description: "Kelola proyek lintas jenis industri.",
  },
  {
    href: "/rab",
    label: "RAB",
    icon: Calculator,
    description: "Rencana anggaran biaya, versi, dan approval.",
  },
  {
    href: "/katalog-harga",
    label: "Katalog Harga",
    icon: Tags,
    description: "Harga barang/jasa beserta sumber dan status verifikasi.",
  },
  {
    href: "/klien",
    label: "Klien",
    icon: Building2,
    description: "Data klien dan kontak.",
  },
  {
    href: "/dokumen",
    label: "Dokumen",
    icon: FileText,
    description: "Dokumen terbit, snapshot, dan ekspor PDF/XLSX.",
  },
  {
    href: "/penawaran",
    label: "Penawaran",
    icon: FileSignature,
    description: "Surat penawaran dari RAB yang disetujui.",
  },
  {
    href: "/invoice",
    label: "Invoice & Pembayaran",
    icon: Receipt,
    description: "Invoice, termin, dan pencatatan pembayaran.",
  },
  {
    href: "/spk-bast",
    label: "SPK & BAST",
    icon: Handshake,
    description: "Surat perintah kerja dan berita acara serah terima.",
  },
  {
    href: "/approval",
    label: "Approval",
    icon: ClipboardCheck,
    description: "Antrian persetujuan RAB dan dokumen.",
  },
  {
    href: "/pengaturan",
    label: "Pengaturan",
    icon: Settings,
    description: "Profil perusahaan, pengguna, role, dan template.",
  },
];

export function findNavItem(pathname: string): NavItem | undefined {
  if (pathname === "/") return NAV_ITEMS[0];
  return NAV_ITEMS.find(
    (item) => item.href !== "/" && (pathname === item.href || pathname.startsWith(`${item.href}/`)),
  );
}

export function isActive(item: NavItem, pathname: string): boolean {
  return findNavItem(pathname)?.href === item.href;
}
