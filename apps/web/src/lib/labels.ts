import type { BadgeTone } from "@/components/ui/StatusBadge";
import type {
  AiRunKind,
  AiRunStatus,
  AiState,
  ApprovalAction,
  BastKind,
  ClientType,
  ClientResponse,
  DocAction,
  DocStatus,
  DocumentStatus,
  DocumentType,
  PaymentMethod,
  PaymentState,
  MatchLevel,
  ObservationSource,
  PriceSourceType,
  ProjectStatus,
  ProjectType,
  RabAction,
  RabItemType,
  RabStatus,
  VerificationStatus,
} from "./types";

export const PROJECT_STATUS: Record<ProjectStatus, { label: string; tone: BadgeTone }> = {
  prospect: { label: "Prospek", tone: "neutral" },
  active: { label: "Berjalan", tone: "success" },
  on_hold: { label: "Ditunda", tone: "warning" },
  completed: { label: "Selesai", tone: "success" },
  cancelled: { label: "Dibatalkan", tone: "danger" },
};

export const PROJECT_TYPE: Record<ProjectType, string> = {
  construction: "Konstruksi & renovasi",
  fabrication: "Fabrikasi & mekanik",
  procurement: "Pengadaan barang",
  it: "IT & perangkat lunak",
  professional_services: "Jasa profesional",
  operations: "Operasional",
  other: "Lainnya",
};

export const CLIENT_TYPE: Record<ClientType, string> = {
  company: "Perusahaan",
  individual: "Perorangan",
  government: "Instansi pemerintah",
  other: "Lainnya",
};

const AUDIT_ACTIONS: Record<string, string> = {
  "quotation.create": "membuat penawaran",
  "quotation.update": "mengubah penawaran",
  "quotation.terms": "mengubah jadwal pembayaran",
  "quotation.submit": "mengajukan review penawaran",
  "quotation.withdraw": "menarik pengajuan penawaran",
  "quotation.approve": "menyetujui penawaran",
  "quotation.reject": "menolak penawaran",
  "quotation.reopen": "membuka kembali penawaran",
  "quotation.respond": "mencatat tanggapan klien",
  "quotation.void": "membatalkan penawaran",
  "quotation.delete": "menghapus penawaran",
  "invoice.create": "membuat invoice",
  "invoice.update": "mengubah invoice",
  "invoice.submit": "mengajukan review invoice",
  "invoice.withdraw": "menarik pengajuan invoice",
  "invoice.approve": "menyetujui invoice",
  "invoice.reject": "menolak invoice",
  "invoice.reopen": "membuka kembali invoice",
  "invoice.void": "membatalkan invoice",
  "invoice.delete": "menghapus invoice",
  "payment.record": "mencatat pembayaran",
  "payment.allocate": "mengalokasikan pembayaran",
  "payment.void": "membatalkan pembayaran",
  "spk.create": "membuat SPK",
  "spk.update": "mengubah SPK",
  "spk.submit": "mengajukan review SPK",
  "spk.withdraw": "menarik pengajuan SPK",
  "spk.approve": "menyetujui SPK",
  "spk.reject": "menolak SPK",
  "spk.reopen": "membuka kembali SPK",
  "spk.void": "membatalkan SPK",
  "spk.delete": "menghapus SPK",
  "bast.create": "membuat BAST",
  "bast.update": "mengubah BAST",
  "bast.submit": "mengajukan review BAST",
  "bast.withdraw": "menarik pengajuan BAST",
  "bast.approve": "menyetujui BAST",
  "bast.reject": "menolak BAST",
  "bast.reopen": "membuka kembali BAST",
  "bast.void": "membatalkan BAST",
  "bast.delete": "menghapus BAST",
  "ai_run.create": "meminta draft ke asisten AI",
  "ai_run.apply": "menerapkan hasil asisten AI",
  "ai_run.discard": "membuang hasil asisten AI",
  "rab_item.ai_apply": "Menambah item dari asisten AI",
  "document.issue": "menerbitkan dokumen",
  "document.void": "membatalkan dokumen",
  "document_settings.update": "mengubah template dokumen",
  "rab_item.import": "mengimpor item RAB",
  "auth.login": "Masuk",
  "auth.logout": "Keluar",
  "auth.password_changed": "Mengganti kata sandi",
  "auth.password_reset_cli": "Kata sandi disetel ulang (CLI)",
  "auth.switch_organization": "Berpindah organisasi",
  "organization.bootstrap": "Organisasi dibuat",
  "organization.update": "Mengubah profil perusahaan",
  "member.add": "Menambah pengguna",
  "member.update": "Mengubah pengguna",
  "client.create": "Menambah klien",
  "client.update": "Mengubah klien",
  "client.delete": "Menghapus klien",
  "project.create": "Membuat proyek",
  "project.update": "Mengubah proyek",
  "project.status_change": "Mengubah status proyek",
  "project.members_update": "Mengubah anggota proyek",
  "project.delete": "Menghapus proyek",
  "rab.create": "Membuat RAB",
  "rab.update": "Mengubah judul RAB",
  "rab.delete": "Menghapus RAB",
  "rab.duplicate": "Menggandakan RAB",
  "rab_version.create": "Membuat versi RAB baru",
  "rab_version.update": "Mengubah pajak/diskon RAB",
  "rab_version.submit": "Mengajukan RAB untuk review",
  "rab_version.withdraw": "Menarik kembali RAB",
  "rab_version.approve": "Menyetujui RAB",
  "rab_version.reject": "Menolak RAB",
  "rab_version.reopen": "Membuka kembali RAB",
  "rab_version.archive": "Mengarsipkan versi RAB",
  "rab_item.create": "Menambah item RAB",
  "rab_item.update": "Mengubah item RAB",
  "rab_item.delete": "Menghapus item RAB",
  "supplier.create": "Menambah supplier",
  "supplier.update": "Mengubah supplier",
  "catalog_item.create": "Menambah item katalog",
  "catalog_item.update": "Mengubah item katalog",
  "price_observation.create": "Mencatat harga",
  "price_observation.verify": "Memverifikasi harga",
  "price_observation.reject": "Menolak harga",
  "price_import.commit": "Mengimpor harga",
};

export function auditActionLabel(action: string): string {
  return AUDIT_ACTIONS[action] ?? action;
}

export function options<K extends string>(record: Record<K, string | { label: string }>) {
  return (Object.keys(record) as K[]).map((value) => {
    const entry = record[value];
    return { value, label: typeof entry === "string" ? entry : entry.label };
  });
}

export const FIELD_LABELS: Record<string, string> = {
  subject: "Perihal",
  valid_until: "Berlaku sampai",
  introduction: "Pembuka",
  terms: "Ketentuan",
  payment_terms: "Jadwal pembayaran",
  client_response: "Tanggapan klien",
  grand_total: "Total",
  due_date: "Jatuh tempo",
  amount: "Jumlah",
  allocations: "Alokasi",
  allocation: "Alokasi",
  total_amount: "Nilai",
  void_reason: "Alasan pembatalan",
  tagline: "Tagline",
  accent_color: "Warna aksen",
  footer_text: "Teks kaki",
  rab_terms: "Ketentuan RAB",
  show_item_codes: "Tampilkan kode item",
  show_price_sources: "Tampilkan sumber harga",
  show_amount_in_words: "Tampilkan terbilang",
  payment_bank_name: "Bank",
  payment_account_number: "Nomor rekening",
  payment_account_holder: "Atas nama rekening",
  spk_terms: "Ketentuan SPK",
  bast_terms: "Ketentuan BAST",
  contract_value: "Nilai kontrak",
  client_signatory_name: "Penanda tangan pemberi kerja",
  client_signatory_title: "Jabatan pemberi kerja",
  company_signatory_name: "Penanda tangan pelaksana",
  company_signatory_title: "Jabatan pelaksana",
  handover_date: "Tanggal serah terima",
  delivered_by_name: "Yang menyerahkan",
  delivered_by_title: "Jabatan yang menyerahkan",
  received_by_name: "Yang menerima",
  received_by_title: "Jabatan yang menerima",
  condition: "Kondisi",
  items: "Item",
  name: "Nama",
  code: "Kode",
  number: "Nomor",
  client_type: "Jenis klien",
  project_type: "Jenis proyek",
  client_id: "Klien",
  owner_id: "Penanggung jawab",
  status: "Status",
  description: "Deskripsi",
  scope: "Ruang lingkup",
  location: "Lokasi",
  start_date: "Tanggal mulai",
  end_date: "Tanggal selesai",
  currency: "Mata uang",
  tax_label: "Label pajak",
  tax_rate_percent: "Tarif pajak",
  budget_amount: "Anggaran",
  notes: "Catatan",
  attributes: "Atribut tambahan",
  members: "Anggota",
  tax_id: "NPWP",
  email: "Email",
  phone: "Telepon",
  address: "Alamat",
  city: "Kota",
  contact_person: "Kontak",
  is_active: "Aktif",
  role: "Role",
  legal_name: "Nama badan usaha",
  website: "Website",
  title: "Judul",
  quantity: "Kuantitas",
  unit: "Satuan",
  unit_price: "Harga satuan",
  item_type: "Jenis item",
  category: "Kategori",
  specification: "Spesifikasi",
  price_source: "Sumber harga",
  price_source_type: "Jenis sumber harga",
  discount_type: "Jenis diskon",
  discount_value: "Nilai diskon",
  assumptions: "Asumsi",
  based_on_version: "Berdasarkan versi",
  note: "Catatan",
  price: "Harga",
  verification_status: "Status verifikasi",
  price_observation_id: "Harga katalog",
  brand: "Merek",
  items_created: "Item baru",
  prices_created: "Harga tercatat",
  suppliers_created: "Supplier baru",
};

export const RAB_STATUS: Record<RabStatus, { label: string; tone: BadgeTone }> = {
  draft: { label: "Draft", tone: "neutral" },
  in_review: { label: "Menunggu review", tone: "warning" },
  approved: { label: "Disetujui", tone: "success" },
  rejected: { label: "Ditolak", tone: "danger" },
  archived: { label: "Diarsipkan", tone: "neutral" },
};

export const RAB_ACTION: Record<
  RabAction,
  { label: string; noteLabel: string; noteRequired: boolean; danger?: boolean }
> = {
  submit: {
    label: "Ajukan review",
    noteLabel: "Catatan untuk reviewer (opsional)",
    noteRequired: false,
  },
  withdraw: { label: "Tarik kembali", noteLabel: "Alasan (opsional)", noteRequired: false },
  approve: { label: "Setujui", noteLabel: "Catatan persetujuan (opsional)", noteRequired: false },
  reject: { label: "Tolak", noteLabel: "Alasan penolakan", noteRequired: true, danger: true },
  reopen: {
    label: "Buka kembali untuk revisi",
    noteLabel: "Catatan (opsional)",
    noteRequired: false,
  },
  archive: { label: "Arsipkan", noteLabel: "Alasan (opsional)", noteRequired: false, danger: true },
};

export const RAB_ITEM_TYPE: Record<RabItemType, string> = {
  material: "Material/barang",
  labor: "Tenaga kerja",
  service: "Jasa",
  equipment: "Peralatan",
  transport: "Transportasi",
  overhead: "Overhead",
  other: "Lain-lain",
};

export const PRICE_SOURCE_TYPE: Record<PriceSourceType, string> = {
  manual: "Input manual",
  catalog: "Katalog internal",
  history: "Riwayat proyek",
  vendor_quote: "Penawaran vendor",
  import: "Impor spreadsheet/dokumen",
  external: "Sumber eksternal",
};

export const APPROVAL_ACTION: Record<ApprovalAction, string> = {
  submitted: "mengajukan review",
  withdrawn: "menarik kembali pengajuan",
  approved: "menyetujui",
  rejected: "menolak",
  reopened: "membuka kembali untuk revisi",
  archived: "mengarsipkan",
  superseded: "menandai sebagai digantikan versi baru",
};

export const VERIFICATION_STATUS: Record<VerificationStatus, { label: string; tone: BadgeTone }> = {
  unverified: { label: "Belum terverifikasi", tone: "warning" },
  verified: { label: "Terverifikasi", tone: "success" },
  rejected: { label: "Ditolak", tone: "danger" },
};

export const OBSERVATION_SOURCE: Record<ObservationSource, string> = {
  manual: "Input manual",
  vendor_quote: "Penawaran vendor",
  import: "Impor spreadsheet",
  external: "Sumber eksternal",
};

export const MATCH_LEVEL: Record<MatchLevel, { label: string; tone: BadgeTone }> = {
  high: { label: "Cocok tinggi", tone: "success" },
  medium: { label: "Cocok sedang", tone: "warning" },
  low: { label: "Cocok rendah", tone: "neutral" },
};

export const DOCUMENT_STATUS: Record<DocumentStatus, { label: string; tone: BadgeTone }> = {
  issued: { label: "Terbit", tone: "success" },
  void: { label: "Dibatalkan", tone: "danger" },
};

export const DOCUMENT_TYPE: Record<DocumentType, string> = {
  rab: "RAB",
  quotation: "Penawaran",
  invoice: "Invoice",
  spk: "SPK",
  bast: "BAST",
};

export const DOC_STATUS: Record<DocStatus, { label: string; tone: BadgeTone }> = {
  draft: { label: "Draft", tone: "neutral" },
  in_review: { label: "Menunggu review", tone: "warning" },
  approved: { label: "Disetujui", tone: "success" },
  rejected: { label: "Ditolak", tone: "danger" },
  issued: { label: "Terbit", tone: "success" },
  void: { label: "Dibatalkan", tone: "danger" },
};

export const DOC_ACTION: Record<DocAction, { label: string; danger?: boolean; noteRequired?: boolean }> = {
  submit: { label: "Ajukan review" },
  withdraw: { label: "Tarik pengajuan" },
  approve: { label: "Setujui" },
  reject: { label: "Tolak", danger: true, noteRequired: true },
  reopen: { label: "Kembalikan ke draft" },
};

export const CLIENT_RESPONSE: Record<ClientResponse, { label: string; tone: BadgeTone }> = {
  accepted: { label: "Diterima klien", tone: "success" },
  declined: { label: "Ditolak klien", tone: "danger" },
};

export const PAYMENT_STATE: Record<PaymentState, { label: string; tone: BadgeTone }> = {
  unpaid: { label: "Belum dibayar", tone: "warning" },
  partial: { label: "Dibayar sebagian", tone: "warning" },
  paid: { label: "Lunas", tone: "success" },
};

export const BAST_KIND: Record<BastKind, string> = {
  partial: "Serah terima sebagian",
  final: "Serah terima akhir",
};

export const AI_RUN_KIND: Record<AiRunKind, string> = {
  rab_draft: "Draft dari deskripsi",
  extract_items: "Ekstraksi dari teks",
  extract_document: "Ekstraksi dari berkas",
};

export const AI_RUN_STATUS: Record<AiRunStatus, { label: string; tone: BadgeTone }> = {
  queued: { label: "Antre", tone: "neutral" },
  running: { label: "Diproses", tone: "warning" },
  succeeded: { label: "Siap ditinjau", tone: "success" },
  failed: { label: "Gagal", tone: "danger" },
  applied: { label: "Diterapkan", tone: "success" },
  discarded: { label: "Dibuang", tone: "neutral" },
};

export const AI_STATE: Record<AiState, { label: string; tone: BadgeTone }> = {
  disabled: { label: "Belum diaktifkan", tone: "neutral" },
  ready: { label: "Siap", tone: "success" },
  unavailable: { label: "Tidak tersedia", tone: "danger" },
  unsafe: { label: "Konfigurasi tidak aman", tone: "danger" },
};

export const PAYMENT_METHOD: Record<PaymentMethod, string> = {
  transfer: "Transfer bank",
  cash: "Tunai",
  cheque: "Cek",
  giro: "Giro",
  other: "Lainnya",
};
