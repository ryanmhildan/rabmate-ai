# RABmate AI — Rencana Proyek

Dokumen ini adalah peta kerja utama. Detail arsitektur ada di [ARCHITECTURE.md](ARCHITECTURE.md),
keputusan teknis di [DECISIONS.md](DECISIONS.md).

## 1. Hasil audit awal (2026-10-18)

| Aspek | Temuan |
|---|---|
| Isi repository | Hanya master prompt (dokumen pribadi, tidak disertakan di repository). Tidak ada kode, belum ada Git. |
| Git | Diinisialisasi pada audit ini (`git init -b main`), belum ada commit. |
| OS | Windows 11 Home 10.0.26200 |
| Node.js / npm | v24.13.0 / 11.6.2 (pnpm tidak terpasang → pakai npm) |
| Python | 3.12.10 (Microsoft Store build), pip 26.1; `uv` tidak terpasang |
| Docker | Docker Desktop 29.4.3, Compose v5.1.3 (daemon perlu dinyalakan manual) |
| WSL2 | `Ubuntu-24.04`, `docker-desktop` tersedia |
| GPU | NVIDIA RTX 4050 Laptop, 6 GB VRAM, driver 617.42 |
| RAM | ±15,2 GB terbaca |
| PostgreSQL lokal (`psql`) | Tidak terpasang → PostgreSQL dijalankan via Docker |
| Hermes Agent | **Belum terpasang** (`hermes` tidak ada di PATH) |
| Ollama | **Belum terpasang** |

## 2. Ruang lingkup MVP

MVP fokus pada alur inti yang dapat dipercaya:

1. Login, organisasi, role/permission, isolasi data per organisasi.
2. Klien dan proyek (multi-industri, atribut tambahan fleksibel).
3. **RAB engine**: item, kalkulasi Decimal deterministik, versi, validasi, approval, snapshot.
4. Katalog harga dengan provenance dan status verifikasi.
5. Impor CSV/XLSX dengan preview; ekspor RAB ke XLSX dan PDF.
6. Dokumen terbit (snapshot immutable) dengan penomoran unik dan idempotensi.
7. Invoice multi-termin dan pembayaran parsial.
8. Adapter Hermes Agent dengan allowlist tools, batas waktu, tanpa fallback cloud.

Di luar MVP (ditunda): OCR penuh, pencarian harga web otomatis, notifikasi email,
multi-mata uang dengan kurs, deployment publik.

## 3. Modul

| Modul | Backend (`services/api/app/modules/…`) | Frontend (`apps/web/src/app/…`) |
|---|---|---|
| Auth & user | `auth`, `users`, `organizations` | `/login`, `/pengaturan` |
| Klien | `clients` | `/klien` |
| Proyek | `projects` | `/proyek` |
| RAB | `rab` (+ `rab/calculation.py` murni) | `/rab` |
| Katalog harga | `pricing` | `/katalog-harga` |
| Impor/ekspor | `imports`, `exports` | dialog impor di RAB/katalog |
| Dokumen | `documents` (template + renderer terpisah) | `/dokumen` |
| Penawaran | `quotations` | `/penawaran` |
| Invoice & pembayaran | `invoices`, `payments` | `/invoice` |
| SPK & BAST | `spk`, `bast` | `/spk-bast` |
| Approval | `approvals` | `/approval` |
| Audit & notifikasi | `audit`, `notifications` | panel aktivitas di dashboard |
| AI | `ai` (adapter, tools, guardrails) | `/asisten` (chat) |

## 4. Tahapan implementasi

Setiap fase selesai hanya jika tes fase tersebut lulus dan dokumentasi diperbarui.

| Fase | Isi | Kriteria penerimaan |
|---|---|---|
| **0 — Audit & rencana** | Audit, dokumen PROJECT_PLAN/ARCHITECTURE/DECISIONS | Dokumen ada, risiko tercatat |
| **1 — Fondasi** | Next.js, FastAPI, PostgreSQL (Docker), config `.env`, SQLAlchemy + Alembic, logging, health check, lint & test | `docker compose up` jalan; `/api/v1/health` melaporkan DB `ok`; migrasi awal teraplikasi; pytest, ruff, eslint, vitest, `next build` lulus |
| **2 — Auth & struktur data** | Organisasi, user, membership, role/permission, sesi cookie + CSRF, klien, proyek, audit log dasar, bootstrap admin via CLI | Tes otorisasi & isolasi organisasi (akses lintas org → 404) lulus; rate limit login |
| **3 — RAB engine** | Tabel RAB/versi/item, kalkulasi Decimal, transisi status, versi & perbandingan, UI RAB | Unit test rumus & edge case; tes transisi status; UI membuat RAB end-to-end |
| **4 — Katalog harga** | Katalog, observasi harga, supplier, provenance, impor spreadsheet, pencarian kandidat | Harga tanpa sumber tidak bisa berstatus terverifikasi; impor menolak baris invalid dengan laporan |
| **5 — Dokumen & ekspor** | PDF/XLSX RAB, template, snapshot, preview, penerbitan idempoten | Dokumen terbit tidak berubah saat RAB berubah; retry penerbitan tidak menggandakan |
| **6 — Penawaran, invoice, termin** | Penawaran, invoice, termin persen/nominal, pembayaran parsial, alokasi, overdue | Tes 30/40/30, pembayaran parsial, sisa tagihan, validasi total termin |
| **7 — SPK & BAST** | Draft → review → approval → issuance, relasi proyek/penawaran | Tes workflow & snapshot |
| **8 — Hermes & model lokal** | Profil Hermes khusus, adapter, MCP tools RABmate, allowlist, timeout, mock adapter | Tes guardrail dengan fake adapter; uji manual dengan model lokal terdokumentasi |
| **9 — Dokumen & AI lanjutan** | Parser PDF/Excel, OCR opsional, ekstraksi terstruktur, preview & verifikasi manusia, chat kontekstual | Tes ekstraksi dengan fixture; nilai tak diketahui tetap `null` |
| **10 — Hardening & rilis MVP** | E2E acceptance test, audit keamanan, review migrasi, polish UI, dokumentasi final, seed demo | Seluruh kriteria MVP (§6) terpenuhi |

## 5. Risiko utama

| # | Risiko | Dampak | Mitigasi |
|---|---|---|---|
| R1 | **Hermes mewajibkan konteks ≥ 64.000 token** dan menolak start jika lebih kecil. Dengan VRAM 6 GB, KV cache 64K untuk model 3–4B (fp16) bisa > 6 GB. | Model lokal lambat (offload ke RAM) atau gagal dimuat | Uji model kecil + kuantisasi KV cache; batasi toolset agar prompt sistem kecil; pemrosesan dokumen bertahap; semua fitur non-AI tetap berfungsi tanpa AI. Tidak ada klaim "berjalan offline" sebelum diuji. |
| R2 | **API server Hermes default memakai toolset penuh** (terminal, file, web, memory). | Agent bisa mengeksekusi perintah shell | Profil Hermes khusus `rabmate` dengan seluruh toolset bawaan dinonaktifkan; hanya MCP server RABmate yang di-allowlist (`tools.include`); diverifikasi via `GET /v1/toolsets` sebelum dipakai. |
| R3 | Model kecil tidak andal melakukan tool calling multi-langkah. | Draft AI salah/terputus | Mode "structured completion": backend menyiapkan konteks sendiri, AI hanya mengembalikan JSON yang divalidasi Pydantic. Agentic tool-calling opsional. |
| R4 | Konteks pengguna/organisasi tidak otomatis terbawa ke panggilan MCP tool. | Kebocoran data lintas org | *Tool grant* berumur pendek per percakapan, dibuat backend, terikat user+org+proyek+daftar tool; tool hanya bisa baca/draft. Detail di ARCHITECTURE §5. |
| R5 | Prompt injection dari dokumen pengguna. | AI mengikuti instruksi berbahaya | Isi dokumen diberi pembatas dan diperlakukan sebagai data; tool tidak punya aksi final; semua perubahan butuh konfirmasi pengguna. |
| R6 | Perhitungan uang tidak konsisten (float, pembulatan). | Angka RAB/invoice salah | `Decimal` + `NUMERIC` di DB; satu modul kalkulasi murni di backend; frontend hanya menampilkan hasil backend. |
| R7 | Library PDF/OCR di Windows butuh dependensi native (GTK, Tesseract). | Instalasi gagal | Pilih library pure-Python untuk PDF (dievaluasi di fase 5); OCR opsional dan terdeteksi saat runtime. |
| R8 | Versi dependensi sangat baru (Next 16, TypeScript 7, ESLint 10). | Inkompatibilitas tooling | Gunakan versi yang dipilih `create-next-app`, kunci dengan lockfile, catat di DECISIONS. |
| R9 | Satu developer, cakupan besar. | Fitur setengah jadi | Fase berurutan, tidak ada tombol tanpa fungsi; fitur belum siap ditandai "belum tersedia". |

## 6. Kriteria MVP selesai

Mengacu pada master prompt §17. Checklist dilacak di sini:

- [x] Frontend & backend berjalan lokal (fondasi, Fase 1)
- [x] Login
- [x] Proyek & klien
- [x] RAB manual
- [x] Kalkulasi RAB benar & teruji
- [x] Katalog harga dengan sumber & status verifikasi
- [x] Impor/ekspor RAB berfungsi
- [x] PDF RAB dari data aktual
- [x] Versi RAB jelas
- [x] Approval & snapshot dokumen (approval RAB di Fase 3; dokumen RAB terbit + snapshot di Fase 5;
      penawaran/invoice/SPK/BAST memakai mekanisme yang sama di Fase 6–7)
- [x] Adapter AI dengan batas permission & error handling (ADR-040/041; loopback + toolset fail
      closed, tool read-only dengan izin pengguna; `test_ai_adapter.py`, `test_ai_api.py`)
- [x] Integrasi Hermes terdokumentasi & dapat diuji (LOCAL_DEVELOPMENT §7; stub Hermes untuk E2E
      tanpa model; diuji dengan Hermes 0.22.2 + model lokal)
- [x] Model lokal teruji terpisah dari business engine (adapter palsu di semua tes; uji model nyata
      §7.4/§7.7; kegagalan model tidak menyentuh data bisnis)
- [x] Tes penting lulus (Fase 10: backend 513, frontend 167, termasuk tes penerimaan 11 langkah)
- [x] Tidak ada secrets terkomit (pemindaian Fase 10, [SECURITY.md](SECURITY.md); belum ada commit)
- [x] README cukup untuk developer lain (mulai cepat, data demo, keamanan, deployment)
- [x] Tidak ada tombol utama yang hanya mock (perancah "Modul belum tersedia" dihapus; fitur yang
      memang belum dikonfigurasi — pencarian harga eksternal, OCR — menyatakannya terus terang)

## 7. Status fase

| Fase | Status |
|---|---|
| 0 | Selesai (2026-10-18) |
| 1 | Selesai (2026-10-18) — lihat ringkasan di bawah |
| 2 | Selesai (2026-10-18) — lihat ringkasan di bawah |
| 3 | Selesai (2026-10-19) — lihat ringkasan di bawah |
| 4 | Selesai (2026-10-19) — lihat ringkasan di bawah |
| 5 | Selesai (2026-10-19) — lihat ringkasan di bawah |
| 6 | Selesai (2026-10-19) — lihat ringkasan di bawah |
| 7 | Selesai (2026-10-19) — lihat ringkasan di bawah |
| 8 | Selesai (2026-10-20) — teruji dengan mock/stub dan model lokal sungguhan (Hermes 0.22.2 + Ollama `qwen2.5:3b`, jendela 32K yang dinyatakan 64K atas keputusan pengguna) |
| 9 | Selesai (2026-10-20) — import PDF/XLSX/CSV (OCR opsional, Tesseract belum dipasang) dan chat proyek bersumber; teruji dengan mock dan model lokal |
| 10 | Selesai (2026-10-21) — hardening, tes penerimaan & E2E, validasi migrasi, data demo lengkap, dokumentasi final; **MVP selesai** |

### Ringkasan Fase 1

Yang dibangun:
- **Backend** `services/api`: app factory FastAPI, konfigurasi `pydantic-settings` (guard produksi
  untuk `SECRET_KEY`, CORS tanpa wildcard), logging dengan redaksi secrets, format error seragam
  tanpa stack trace, request ID, security headers, SQLAlchemy 2.1 + psycopg 3, Alembic (revisi
  baseline `0001`), `GET /api/v1/health` (cek DB, 503 bila DB mati) dan `/api/v1/health/live`.
- **Frontend** `apps/web`: shell aplikasi responsif (sidebar 11 menu, drawer mobile, breadcrumb),
  dashboard dengan panel status sistem dari API nyata, halaman modul yang belum dibangun ditandai
  fasenya (tanpa data palsu), util format Rupiah/tanggal `Asia/Jakarta`, klien API dengan parsing
  format error, TanStack Query.
- **Infra/DX**: Docker Compose PostgreSQL 17 (bind 127.0.0.1, DB tes otomatis), `.env.example`,
  `scripts/setup.ps1`, `dev.ps1`, `check.ps1`.

Verifikasi Fase 1: backend 23 tes, frontend 28 tes, `next build` lulus; stack lokal dicek di
browser (DB terhubung/terputus). Perintah ulang ada di
[LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md#5-pengujian).

### Ringkasan Fase 2

Yang dibangun:
- **Identitas & akses:** organisasi, user (Argon2id), membership + 6 role → permission (ADR-017),
  sesi server-side via cookie HttpOnly + CSRF terikat sesi, cek `Origin`, throttle login berbasis DB,
  ganti kata sandi (cabut sesi lain), pindah organisasi, CLI `create-admin`/`set-password`/`seed-demo`.
- **Klien & proyek:** CRUD terisolasi per organisasi, FK komposit klien↔organisasi, optimistic
  locking (`version`), penomoran `PRJ-<tahun>-<urut>` atomik, siklus status eksplisit, anggota
  proyek, atribut fleksibel terbatas (ADR-018), uang sebagai string desimal (ADR-020).
- **Audit:** setiap perubahan penting dicatat dalam transaksi yang sama (aktor, aksi, diff, request
  id), tanpa secrets; endpoint `/audit-logs` dan ringkasan dashboard dari DB.
- **Frontend:** login, guard (`proxy.ts` + `AuthGate`), menu pengguna, halaman Klien, Proyek
  (daftar/buat/detail/ubah/status/anggota/aktivitas), Pengaturan (profil, pengguna & role, log,
  ganti sandi), Dashboard dengan angka nyata.

Verifikasi Fase 2: backend 124 tes (lulus 3× berturut-turut), frontend 75 tes, ruff/mypy strict/
ESLint/tsc bersih, `next build` lulus. Uji manual di browser: redirect ke login dengan `next`,
login gagal/sukses, buat proyek (validasi klien & server), ubah status, anggota, logout, role
Viewer (UI read-only dan API menolak 403 meski dipanggil langsung), tampilan mobile.

Catatan: halaman `(app)` memakai `instant = false` (ADR-019).

### Ringkasan Fase 3 — RAB engine

Yang dibangun:
- **Kalkulasi murni** (`app/modules/rab/calculation.py`): `Decimal` dengan konteks 60 digit,
  pembulatan ROUND_HALF_UP per baris, diskon sebelum pajak, pajak hanya bila dikonfigurasi,
  deteksi overflow terhadap `NUMERIC(20,2)` (ADR-022). Dipakai bersama oleh API, validasi, dan
  (nanti) ekspor serta tools AI.
- **Validasi** (`validation.py`): kesalahan (tanpa item, harga kosong, diskon > subtotal, overflow)
  menghalangi pengajuan; peringatan (harga nol, sumber harga kosong, kode ganda) dan info (pajak
  belum dikonfigurasi) tidak.
- **Versi & approval** (ADR-023): status per versi `draft → in_review → approved | rejected`,
  `withdraw`, `reopen`, `archive`; versi disetujui tidak dapat diubah; revisi = versi baru yang
  menyalin item; menyetujui versi baru mengarsipkan versi lama (`superseded`); hanya satu versi
  terbuka per RAB (dijaga juga oleh unique index parsial). Riwayat di `approval_records`.
- **Konkurensi** (ADR-024): row lock pada versi untuk setiap mutasi, `lock_version` untuk header,
  `row_version` per item.
- **Fitur:** penomoran `RAB-<tahun>-<urut>`, gandakan RAB, bandingkan versi (per item: baru/dihapus/
  berubah/sama + selisih), antrian approval, RAB di halaman proyek, statistik RAB di dashboard,
  proyek dengan RAB tidak dapat dihapus, RAB baru hanya untuk proyek prospek/berjalan/ditunda.
- **UI:** daftar RAB, workspace RAB (tab versi, tabel item, dialog item, pajak & diskon, validasi,
  riwayat persetujuan, aksi status sesuai izin dari server), halaman bandingkan, halaman Approval.

Verifikasi Fase 3: backend 187 tes (lulus 2× berturut-turut), frontend 99 tes, ruff/mypy strict/
ESLint/tsc bersih, `next build` lulus. E2E di browser dengan akun demo: Estimator membuat RAB,
menambah item berharga dan tanpa harga, pengajuan ditolak server dengan daftar item bermasalah,
harga dilengkapi, diskon 5% + PPN 11% (semua total dicek manual), diajukan; Approver melihat antrian
dan menyetujui; Estimator membuat v2, mengubah harga, membandingkan v1↔v2 (selisih benar);
pengubahan v1 yang disetujui lewat API langsung ditolak 409.

Belum termasuk (sesuai rencana): impor item RAB dari spreadsheet (dipindah ke Fase 5 bersama ekspor
XLSX; Fase 4 mengerjakan impor katalog harga), ekspor XLSX/PDF dan snapshot dokumen terbit (Fase 5),
pengurutan ulang item.

### Ringkasan Fase 4 — Katalog harga

Yang dibangun:
- **Model** (migrasi `0004`): supplier, item katalog tanpa harga, riwayat harga append-only
  (`price_observations`) dengan provenance lengkap dan status verifikasi, job impor; tautan
  `rab_items.price_observation_id`. CHECK di DB: harga terverifikasi wajib bersumber (ADR-025).
- **Aturan murni & teruji:** normalisasi satuan (alias `m³`→`m3`, `zak`→`sak`, …; tanpa konversi),
  parsing angka/tanggal Indonesia yang menolak nilai ambigu, skor kecocokan kandidat yang dapat
  dijelaskan (ADR-026).
- **API:** CRUD supplier & item, catat harga, verifikasi/tolak, kandidat harga (katalog + RAB
  disetujui), impor `.xlsx`/`.csv` dengan pratinjau → commit/batal (rumus ditolak, ADR-027), status
  pencarian eksternal yang jujur "belum dikonfigurasi" (ADR-028). Semua mutasi diaudit.
- **RAB:** item dapat ditautkan ke harga katalog; harga & sumber diambil server (ADR-029); status
  verifikasi tampil di tabel item; harga katalog belum terverifikasi menjadi peringatan validasi.
- **UI:** halaman Katalog Harga (tab Item & harga / Supplier, filter, harga terverifikasi vs
  terbaru, banner pencarian eksternal), detail item (riwayat harga, catat harga, verifikasi/tolak,
  tautan sumber aman `noopener noreferrer`, aktivitas), halaman impor (template, unggah, pratinjau
  per baris, simpan/batal, ringkasan hasil), panel **Cari harga** di dialog item RAB (kandidat dengan
  level, alasan, peringatan; satuan berbeda tidak dapat dipakai; lepas tautan).
- **Perbaikan lintas fase:** input desimal di form (harga & kuantitas) kini menolak `95.000` yang
  ambigu (sebelumnya tersimpan sebagai 95) — aturan sama dengan impor.

Verifikasi Fase 4: backend 265 tes, frontend 122 tes, ruff/mypy strict/ESLint/tsc bersih,
`next build` lulus, `alembic check` bersih. E2E di browser dengan akun demo: Estimator menambah
supplier dan item dengan harga awal (input `65.000` ditolak sebagai ambigu), mencatat harga kedua
tanpa sumber, mengimpor CSV 5 baris (3 valid: 2 item baru + 1 harga untuk item yang ada, 1 supplier
baru; baris `4.500` dan `=1+1` dilewati dengan alasan); Approver tidak dapat memverifikasi harga
tanpa sumber (UI dan API 422), memverifikasi harga bersumber, menolak harga impor dengan alasan
(tercatat di audit); Estimator menambah item RAB satuan `zak` lewat **Cari harga** → kandidat
katalog `sak` terverifikasi Rp 65.000 dipakai, subtotal & provenance dari server benar; lewat API
langsung: harga ditolak → 422, satuan berbeda → 422, `unit_price` palsu diabaikan server; kandidat
riwayat RAB v1 tampil dengan keterangan bukan harga pasar terverifikasi.

Belum termasuk: penyedia pencarian harga eksternal (antarmuka siap, sengaja tidak dikonfigurasi),
konversi satuan, impor item RAB dari spreadsheet (Fase 5).

### Ringkasan Fase 5 — Dokumen & ekspor

Yang dibangun:
- **Model** (migrasi `0005`): `document_settings`, `documents` (snapshot JSONB + SHA-256, status
  `issued`/`void`, kunci idempotensi), `document_files` (PDF/XLSX sebagai `bytea`), target versi
  pada `import_jobs`.
- **Snapshot & penerbitan** (ADR-030/031): hanya versi disetujui; idempoten via `Idempotency-Key`
  dan paling banyak satu dokumen berlaku per versi; total diverifikasi ulang; berkas dirender sekali
  dan disimpan; unduhan = byte tersimpan (SHA-256/ETag); pembatalan dengan alasan; nomor
  `RAB-…/V<n>` dan `-R<k>`.
- **Renderer** (ADR-032): PDF ReportLab deterministik (kop perusahaan dari profil, info proyek/klien,
  tabel item berkelompok per kategori dengan subtotal, header berulang tiap halaman, total + diskon
  + DPP + pajak, terbilang Rupiah, catatan/asumsi/ketentuan, blok persetujuan berisi nama & tanggal
  saja, kaki halaman "Halaman X dari Y" + kode verifikasi, watermark PRATINJAU untuk pratinjau,
  halaman mendatar bila kolom sumber harga ditampilkan); XLSX tanpa rumus dan aman dari formula
  injection.
- **Template dokumen** (ADR-034): tagline, warna aksen, teks kaki, ketentuan, opsi kolom, informasi
  pembayaran; tab "Template dokumen" di Pengaturan (ubah: Owner).
- **Impor item RAB** (ADR-033): template xlsx/csv, unggah → pratinjau (subtotal dari server) →
  tambahkan/batalkan, hanya ke versi draft. Pembaca spreadsheet kini dipakai bersama dengan impor
  katalog (`app/shared/spreadsheet.py`).
- **UI:** kartu "Dokumen & ekspor" di workspace RAB (pratinjau PDF, ekspor XLSX, impor item,
  terbitkan dengan dialog yang memakai satu kunci idempotensi per percobaan, daftar dokumen versi),
  halaman Dokumen (filter, unduh) dan detail dokumen (isi snapshot, berkas + SHA-256, integritas,
  batalkan, aktivitas), halaman impor item, statistik dokumen di dashboard.
- **Perbaikan lintas fase:** tautan dashboard `/rab?status=…` kini benar-benar memfilter daftar RAB.

Verifikasi Fase 5: backend 320 tes (39 renderer/unit dokumen, 9 API dokumen, 7 impor item RAB),
frontend 132 tes, ruff/mypy strict/ESLint/tsc bersih, `next build` lulus, migrasi 0005 diuji
naik-turun dan `alembic check` bersih. PDF diperiksa visual (contoh, mendatar, multi-halaman, dan
dokumen nyata). E2E di browser dengan akun demo: Estimator mengunduh pratinjau PDF & ekspor XLSX
versi draft, mengimpor CSV 5 baris (3 masuk; `4.500.000` dan `=10*2` dilewati dengan alasan; total
dihitung ulang benar), melengkapi harga, mengajukan; Approver menyetujui dan menerbitkan
`RAB-2026-0001/V2` (Rp 14.015.886,75); hash berkas yang diunduh = SHA-256 tersimpan; percobaan terbit
dengan kunci lain → 409, versi diarsipkan → 409; Owner mengubah template → dokumen terbit tetap
byte-identik dan snapshot-nya tetap, pratinjau berubah; Owner membatalkan (alasan wajib) lalu
menerbitkan ulang `…/V2-R1` dengan template baru; dashboard menampilkan 1 terbit, 1 dibatalkan.

Catatan: dokumen demo `…/V2` dan `…/V2-R1` dirender sebelum perbaikan lebar kolom total, sehingga
angka total di berkas itu terbungkus dua baris — sengaja tidak dirender ulang (berkas terbit
immutable); dokumen baru memakai tata letak yang sudah diperbaiki.

Belum termasuk: logo perusahaan (menunggu modul unggah berkas), DOCX, penerbitan
penawaran/invoice/SPK/BAST (Fase 6–7), render di background job (belum diperlukan; render RAB
sinkron di bawah 1 detik untuk ratusan item).

### Ringkasan Fase 6 — Penawaran, invoice & termin

Yang dibangun:
- **Model** (migrasi `0006`): penawaran, termin, invoice + baris, pembayaran + alokasi; dokumen
  terbit kini juga untuk penawaran dan invoice.
- **Aturan murni & teruji:** alokasi termin persen/nilai tetap dengan sisa sen ke termin terakhir dan
  pajak proporsional (ADR-035); status bayar & lewat jatuh tempo dari catatan pembayaran (ADR-036);
  alur review bersama dengan izin baru `documents.approve` (ADR-037); total invoice manual memakai
  modul kalkulasi RAB.
- **API:** penawaran dari versi RAB disetujui (nilai disalin), jadwal termin, review, terbit (PDF),
  tanggapan klien, batal/hapus; invoice termin (1 per termin, angka disalin) dan manual (baris +
  pajak dihitung server), review, terbit (nomor saat terbit), batal/hapus; pembayaran dengan
  alokasi, idempotensi, alokasi susulan, pembatalan; ringkasan penagihan di dashboard.
- **PDF:** surat penawaran (item, total, terbilang, tabel termin, ketentuan, masa berlaku) dan
  invoice (rujukan penawaran/termin, baris, total, terbilang, instruksi transfer dari template);
  blok persetujuan hanya nama & tanggal; komponen layout dipakai bersama dengan PDF RAB.
- **UI:** menu Penawaran (daftar, detail: isi, editor termin dengan isi cepat 100% / 50/50 /
  30/40/30, review, terbit, tanggapan klien, invoice per termin, batal/hapus, aktivitas); menu
  Invoice & Pembayaran (daftar dengan filter status/pembayaran/lewat jatuh tempo, invoice manual,
  detail dengan editor baris, review, terbit, catat pembayaran dengan satu kunci idempotensi per
  percobaan, batal pembayaran; tab Pembayaran); tombol "Buat penawaran" di RAB; statistik penagihan
  dan penawaran di dashboard.

Verifikasi Fase 6: backend 347 tes (17 aturan penagihan, 7 API penagihan termasuk 30/40/30,
pembayaran parsial, sisa tagihan, validasi total termin, lewat jatuh tempo, idempotensi, izin,
isolasi), frontend 141 tes, ruff/mypy strict/ESLint/tsc bersih, `next build` lulus, migrasi 0006
diuji naik-turun di DB tes dan `alembic check` bersih. PDF penawaran & invoice diperiksa visual.
E2E di browser dengan akun demo: Estimator membuat PNW-2026-0001 dari RAB-2026-0001 v2
(Rp 14.015.886,75), jadwal 30/40/30 → Rp 4.204.766,03 / 5.606.354,70 / 4.204.766,02 (sisa sen di
termin terakhir; total tepat sama), mengajukan; Approver menyetujui dan menerbitkan; Estimator
mencatat diterima klien; Finance membuat invoice termin 1, Approver menyetujui, Finance
menerbitkan INV-2026-0001, mencatat pembayaran Rp 2.000.000 (sebagian, sisa Rp 2.204.766,03),
percobaan bayar Rp 3.000.000 ditolak (melebihi sisa), pelunasan Rp 2.204.766,03 → Lunas; dashboard
menampilkan diterima bulan ini Rp 4.204.766,03 dan 1 penawaran diterima. Tidak ada respons 5xx.

Insiden saat pengembangan (dilaporkan apa adanya): rantai perintah `alembic upgrade && alembic
downgrade` yang keluarannya dipipa ke `tail` membuat kegagalan upgrade 0006 tidak menghentikan
rantai, sehingga `downgrade -1` berjalan di **database dev** dan menghapus tabel Fase 5 beserta isinya
(dokumen demo RAB-2026-0001/V2 dan /V2-R1 serta template dokumen hasil E2E). Data bisnis lain tidak
tersentuh dan DB tes terpisah. Skema dipulihkan; template disimpan ulang dan dokumen
RAB-2026-0001/V2 diterbitkan ulang lewat UI. Sejak itu uji naik-turun migrasi hanya dijalankan di DB
tes dan perintah memakai `set -o pipefail`.

Belum termasuk: SPK & BAST (Fase 7), retensi/uang jaminan sebagai jenis termin khusus, faktur pajak
resmi (nomor seri pajak tidak dibuat — di luar cakupan dan tidak boleh dikarang), notifikasi jatuh
tempo, multi-mata-uang dalam satu pembayaran.

### Ringkasan Fase 7 — SPK & BAST

Yang dibangun:
- **Model** (migrasi `0007`): `spk_documents`, `bast_documents`, `bast_items`; dokumen terbit kini juga
  untuk SPK dan BAST; template menambah ketentuan SPK/BAST. Kolom alur review dipakai bersama dengan
  penawaran/invoice (`WorkflowColumns`).
- **Aturan:** SPK hanya dari penawaran terbit yang diterima klien, satu SPK aktif per penawaran, nilai
  kontrak & termin dari penawaran (ADR-038); BAST sebagian/akhir (satu akhir per SPK), baris merujuk
  item kontrak atau di luar kontrak, volume kumulatif BAST terbit ≤ volume kontrak — dicek saat simpan,
  ajukan, dan ulang saat terbit dengan mengunci SPK (ADR-039). Penanda tangan, ketentuan, dan kondisi
  barang hanya dari isian pengguna; tidak ada tanda tangan/stempel/klausul yang dibuat aplikasi.
- **Alur:** draft → review → disetujui/ditolak → terbit → batal, izin `projects.write` (penyusun),
  `documents.approve`, `documents.issue`; nomor `SPK-`/`BAST-YYYY-NNNN` saat terbit; penerbitan
  idempoten. Penawaran dengan SPK aktif tidak dapat dibatalkan; SPK dengan BAST aktif tidak dapat
  dibatalkan.
- **PDF:** SPK (para pihak, referensi penawaran/RAB, periode, lokasi, lingkup, rincian volume tanpa
  harga, nilai kontrak + terbilang, jadwal termin, ketentuan, blok tanda tangan kedua pihak berisi
  nama ketikan pengguna) dan BAST (jenis, tanggal serah terima, tabel volume kontrak / sebelumnya /
  BAST ini / kumulatif / kondisi, blok yang menyerahkan & yang menerima).
- **UI:** menu SPK & BAST (tab SPK | BAST dengan filter), detail SPK (formulir, volume kontrak &
  progres serah terima, daftar BAST, termin + status invoice, para pihak, review, terbit, batal,
  hapus, Buat BAST dengan opsi isi sisa volume), detail BAST (editor baris dengan pemilih item
  kontrak dan sisa volume, error server per baris), tombol "Buat SPK" di penawaran, ketentuan
  SPK/BAST di template dokumen, statistik SPK/BAST di dashboard. Antrian **Approval** kini juga
  menampilkan penawaran, invoice, SPK, dan BAST yang menunggu review.
- **Perbaikan di luar cakupan langsung:** halaman detail dokumen (`/dokumen/{id}`) sebelumnya
  mengasumsikan snapshot RAB sehingga dokumen penawaran/invoice akan gagal dibuka; kini dokumen
  non-RAB menampilkan ringkasan umum + tautan ke sumbernya. Dialog transisi kini menampilkan rincian
  alasan penolakan dari server (mis. field yang belum diisi).

Verifikasi Fase 7: backend 355 tes (5 API SPK/BAST: sumber penawaran diterima, workflow & izin,
idempotensi terbit, batal/hapus, aturan volume per baris, cek ulang kumulatif saat terbit, satu BAST
akhir, isolasi organisasi, dashboard; 3 render PDF termasuk escape teks pengguna dan tanpa klausul
tambahan), frontend 148 tes, ruff/mypy strict/ESLint/tsc bersih, `next build` lulus, migrasi 0007
diuji naik-turun hanya di DB tes dan `alembic check` bersih. PDF SPK & BAST diperiksa visual (lebar
kolom label dan header tabel diperbaiki setelah pemeriksaan). E2E di browser dengan akun demo:
Project Manager membuat SPK dari PNW-2026-0001 (Rp 14.015.886,75), pengajuan tanpa tanggal mulai /
penanda tangan ditolak dengan rincian field, lalu dilengkapi dan diajukan; Approver menyetujui dari
antrian Approval; Finance menerbitkan SPK-2026-0001. PM membuat BAST sebagian: kabel 400 m ditolak
per baris (kontrak 305 m), dikoreksi 200 m + instalasi 20 titik + 1 baris di luar kontrak; Approver
menyetujui, Finance menerbitkan BAST-2026-0001; sisa kontrak menjadi kabel 105 m dan instalasi 28
titik. Draft BAST akhir dengan isi otomatis sisa volume diperiksa PDF-nya lalu dihapus. Tidak ada
respons 5xx.

Belum termasuk: adendum/perubahan kontrak (volume tambah-kurang) — saat ini perubahan lingkup berarti
membatalkan SPK dan membuat penawaran/SPK baru; lampiran foto/berkas pada BAST (menunggu modul unggah
berkas); tanda tangan elektronik tersertifikasi (di luar cakupan); keterkaitan otomatis termin
"setelah BAST" dengan pembuatan invoice (penagihan tetap keputusan pengguna).

### Ringkasan Fase 8 — Hermes Agent dan model lokal

Verifikasi Hermes (dokumentasi resmi v0.22.2, rilis 15 Okt 2026, diakses 2026-10-19):

- Integrasi yang tersedia: API server OpenAI-compatible (`/v1/chat/completions`, Responses, Runs
  + SSE, `/v1/toolsets`, `/health`) dengan kunci wajib dan bind `127.0.0.1:8642`; MCP client;
  CLI. Tidak ada Python SDK untuk di-embed.
- Konteks minimum 64K token. Ollama di bawah 24 GB VRAM default 4K, sehingga perlu
  `OLLAMA_CONTEXT_LENGTH=64000`.
- API server menjalankan toolset penuh secara default. Detail di ADR-040.

Di mesin ini **Hermes, Ollama, dan uv belum terpasang**; GPU RTX 4050 6 GB terdeteksi.

Yang dibangun:

- **Adapter** (`app/ai/`):
  - Interface sempit dengan `HermesAdapter` (`httpx2`).
  - Hanya URL loopback; proxy sistem diabaikan.
  - Cek `/v1/toolsets` sebelum setiap permintaan, fail closed.
  - Timeout, retry terbatas, batas ukuran.
  - Tanpa fallback cloud; log tanpa isi.
  - Status `disabled`/`ready`/`unavailable`/`unsafe` di `/ai/status` dan `/health`.
- **Tool registry read-only ber-allowlist**: `get_project_details`, `get_rab_version` —
  Pydantic strict, izin pengguna, log tanpa isi.
- **Workflow** (ADR-041):
  - Draft RAB dari deskripsi (tanpa harga; volume hanya bila tertulis).
  - Ekstraksi item dari teks tempelan: angka disalin model, dicek ada di teks, di-parse
    deterministik sesuai format Indonesia/Inggris; selisih jumlah ditandai; injeksi instruksi di
    dokumen diperlakukan sebagai data.
- **Eksekusi job**: `ai_runs` (migrasi `0008`) diproses di latar belakang dengan status di DB.
  - Satu run aktif per organisasi; run macet kedaluwarsa.
  - Ditolak di awal bila AI tidak siap/tidak aman.
  - Satu kali perbaikan format, lalu gagal rapi tanpa menyentuh data bisnis.
- **Penerapan**: hanya oleh pengguna (`ai.use` + `rab.write`) ke versi draft.
  - Harga katalog di-resolve server, atau harga dokumen ditandai "belum diverifikasi".
  - Total dihitung mesin RAB; idempoten.
  - Izin baru `ai.use` untuk Owner, PM, dan Estimator.
- **UI**:
  - Kartu "Asisten AI lokal" di halaman RAB: status, permintaan draft/ekstraksi, riwayat dengan
    polling.
  - Dialog tinjauan: centang per baris, edit nama/volume/satuan/jenis, pilihan harga, panel
    kandidat katalog, kutipan baris sumber, peringatan, "Data yang dipakai AI", buang hasil.
  - Status AI di dashboard.
- **Pengujian tanpa model**: transport HTTP palsu, adapter palsu, dan `tests/hermes_stub.py`
  (server tiruan khusus pengujian, bukan AI) untuk E2E browser.
- **Panduan setup** Hermes + Ollama dengan `HERMES_HOME` terpisah, termasuk analisis memori 6 GB
  (LOCAL_DEVELOPMENT §7).

Verifikasi Fase 8:

- Backend 433 tes (setelah uji model lokal):
  - 33 adapter: loopback, toolset tidak aman, kunci, retry/timeout, format jawaban, pesan error Hermes.
  - 27 aturan: angka ID/EN, JSON, pasca-proses, registry.
  - 10 API: draft → tinjau → terapkan dengan harga katalog, ekstraksi dengan harga dokumen,
    kegagalan model tanpa merusak RAB, perbaikan format, sibuk/kedaluwarsa, batas input,
    izin/isolasi, allowlist tool, status, penolakan saat tidak siap.
  - 1 matriks izin.
- Frontend 154 tes. ruff/mypy strict/ESLint/tsc bersih, `next build` lulus.
- Migrasi 0008 diuji naik-turun hanya di DB tes; `alembic check` bersih.

E2E di browser dengan akun demo:

- **AI nonaktif**: kartu menampilkan "Belum diaktifkan" tanpa formulir.
- **Dengan stub Hermes** lewat adapter HTTP sungguhan:
  - Ekstraksi penawaran 3 baris menampilkan kutipan baris, harga dokumen, dan peringatan
    100 × 2.500 ≠ 260.000.
  - 3 item diterapkan; subtotal Konektor dihitung mesin RAB Rp 250.000 dan total RAB
    Rp 1.733.265 (termasuk PPN 11%).
  - Draft dari deskripsi: volume 24 dan 1 diambil dari teks, satu baris "belum diketahui";
    hasil dibuang.
- **Stub dengan `terminal` aktif**: status "Konfigurasi tidak aman", formulir hilang, dan POST
  langsung ke API ditolak 503.
- **Hermes mati**: status "tidak tersedia" dengan petunjuk, `/health` tetap 200, fitur non-AI
  berjalan.
- Log hanya berisi kode status dan nama kelas error. Tidak ada respons 5xx.

Pemasangan nyata (atas persetujuan pengguna):

- **Terpasang:** Ollama 0.40.6 (installer resmi, bertanda tangan Ollama Inc.), `qwen2.5:3b`, dan
  Hermes Agent 0.22.2.
  - Hermes dipasang di `%USERPROFILE%\hermes-rabmate` dengan `HERMES_HOME` sendiri, karena
    `AppData` ter-virtualisasi untuk proses dari Claude Desktop.
  - Home global Hermes tidak dibuat atau diubah.
- **Profil dikonfigurasi lewat `hermes config set`:**
  - telemetri mati;
  - provider Ollama lokal;
  - `platform_toolsets.api_server: []`;
  - `max_turns` 4;
  - API server `127.0.0.1:8642` dengan kunci acak.
- **Terverifikasi:**
  - bind lokal saja;
  - 401 tanpa kunci;
  - 0 dari 27 toolset aktif;
  - status RABmate `ready`;
  - permintaan dari UI sampai ke Hermes, dan penolakan Hermes tampil sebagai alasan run gagal
    (adapter kini meneruskan pesan error Hermes yang dipotong; 1 tes baru).
- **Penolakan awal:** Hermes menolak `qwen2.5:3b` karena konteks maksimal model 32.768 token,
  sedangkan syaratnya ≥ 64.000. Rekomendasi `qwen2.5:3b` di versi awal dokumen ini keliru dan
  sudah dikoreksi (LOCAL_DEVELOPMENT §7.2).
- **Keputusan pengguna (2026-10-20):** tetap `qwen2.5:3b` dengan `model.ollama_num_ctx: 64000`
  dinyatakan di profil RABmate. Jendela nyata 32.768.
  - Lewat API, Ollama hanya melayani 4.096 token. Karena itu dibuat varian lokal
    `rabmate-qwen2.5-3b-32k` (Modelfile `num_ctx 32768`, `temperature 0`).
  - Batasan dicatat di LOCAL_DEVELOPMENT §7.2.
- **Perbaikan dari uji nyata:**
  - Instruksi dipindah ke pesan pengguna, karena Hermes menaruh system prompt API setelah
    persona ±1.050 token-nya.
  - Contoh JSON memakai placeholder, karena contoh `"source_line": 3` ditiru model.
  - Angka harus cocok sebagai angka utuh: "0" tidak lagi "ditemukan" di "3.850.000".
  - Angka yang tidak ada di baris item dikosongkan; ini juga menolak injeksi 900.000.
  - Nomor baris dikoreksi berdasarkan nama item.
  - Angka yang diformat ulang model diganti teks angka dokumen.
  - "-" diperlakukan sebagai tidak tertulis; field "belum diketahui" diturunkan dari hasil baca.
  - Baris ganda digabung.
  - Pesan error Hermes diteruskan.
  - Tes tidak lagi bergantung pada `.env` pengembang.
- **Hasil uji model lokal** (LOCAL_DEVELOPMENT §7.4):
  - Ekstraksi tabel layak dengan tinjauan: sebagian besar run 5/5 dengan harga benar; injeksi
    selalu tertolak.
  - Draft bebas dari deskripsi lemah dengan model 3B.
  - Satu hasil ekstraksi diterapkan ke RAB lewat dialog, dengan total dihitung mesin RAB.

Belum termasuk:

- **Model dengan jendela ≥ 64K yang sebenarnya.** Misalnya `gemma3:4b` atau model lebih besar,
  untuk kualitas draft yang lebih baik dan alur agen.
- **Mode agentic/MCP dan chat kontekstual** (Fase 9).
- **PDF/Excel/OCR sebagai sumber ekstraksi** (Fase 9). Saat ini teks ditempel.
- **Streaming jawaban.** Polling status dipilih karena lebih sederhana dan aman.

### Ringkasan Fase 9 — Import dokumen (PDF/Excel/OCR) & chat proyek

Yang dibangun:

- **Dokumen sumber** (ADR-043, migrasi `0009`, `app/modules/intake/`):
  - Unggah ke proyek dengan batas ukuran (dibaca terbatas), deteksi jenis dari isi file +
    ekstensi harus cocok, batas zip bomb XLSX, nama file hanya tampilan, dedup SHA-256 per proyek,
    isi di PostgreSQL; daftar, metadata, teks terbaca, unduh (`attachment` + `nosniff`).
  - Pembaca: PDF (pypdf *layout*, kolom → `" | "`, halaman scan → OCR), XLSX (semua sheet; rumus
    tidak dihitung), CSV/TXT, PNG/JPEG (OCR). Batas halaman/sheet/baris/karakter/piksel/OCR.
  - OCR Tesseract CLI bila terpasang (perintah tetap, tanpa shell, timeout per halaman); bila tidak
    ada, status "OCR tidak tersedia" ditampilkan apa adanya.
- **Workflow `extract_document`**: baris bernomor lintas halaman dengan lokasi untuk manusia
  (Halaman/Sheet + baris), dibagi per bagian (`AI_CHUNK_CHARS`, `AI_MAX_CHUNKS`) dengan kepala tabel
  dibawa ke bagian berikutnya; aturan deterministik Fase 8 per bagian; bagian yang rusak menjadi
  peringatan; ringkasan dokumen (halaman, baris, bagian, halaman OCR, baris tidak diproses).
  Penerapan mencatat sumber harga dan rujukan "Dokumen 'x', Halaman 2, baris 3".
- **Chat proyek** (ADR-044): percakapan privat per proyek; retrieval lewat 4 tool read-only baru
  dengan izin penanya (`get_project_rabs`, `search_catalog`, `get_project_documents`,
  `get_source_document`); sumber bernomor `[S1]…`; data yang tidak disertakan dicatat; pemeriksaan
  bahasa, kutipan, angka vs sumber, atribusi angka ke sumber, klaim "terverifikasi"; jawaban
  disimpan bersama sumber (data persis yang diberikan) dan peringatan.
- **Perbaikan bersama:** eksekusi model dipakai bersama (`with_model`, `complete`, `finish_run`);
  run macet di organisasi dikedaluwarsakan sebelum run baru; run chat tidak bisa dibaca lewat
  `/ai-runs`; `httpx2`, `pypdf`, `pillow` kini dependensi runtime (sebelumnya `httpx2` dan
  `pypdf` hanya di dev — instalasi produksi akan gagal mengimpor adapter Hermes).
- **UI:**
  - Kartu Asisten AI: tab **Ekstraksi dari berkas** (unggah/pilih dokumen proyek, status OCR, format
    angka, unduh asli).
  - Dialog tinjauan: lokasi "Halaman N, baris M", ringkasan dokumen, teks terbaca per halaman,
    catatan AI diberi label sebagai isi dokumen (bukan instruksi), durasi dibulatkan.
  - Halaman proyek: kartu **Tanya asisten AI tentang proyek ini** (percakapan, polling, kutipan,
    sumber + data, sumber "terkait — tidak dikutip AI", peringatan, asumsi, klarifikasi, data yang
    tidak termasuk, hapus percakapan).

Verifikasi Fase 9:

- Backend 503 tes, termasuk:
  - 35 intake tanpa DB: deteksi jenis & penyamaran, nama file, PDF tabel/terkunci/rusak/batas,
    scan dengan/tanpa OCR, XLSX (rumus tidak dihitung), CSV, gambar, Tesseract sebagai perintah
    tetap (tiruan `subprocess`).
  - 23 aturan: penomoran lintas halaman, kepala tabel, pembagian bagian, koreksi baris per
    bagian, penggabungan, prompt chat, cek kutipan/angka/atribusi/verifikasi/bahasa/pengulangan.
  - 12 API: unggah-dedup-unduh-teks, penolakan file, izin & isolasi, ekstraksi berkas →
    terapkan dengan sumber halaman/baris, dokumen panjang per bagian dengan bagian rusak, scan
    tanpa/dengan OCR, dokumen proyek/organisasi lain, status, chat (sumber, peringatan, riwayat,
    sumber terkait), privasi chat, retrieval mengikuti izin, kegagalan/sibuk/503.
- Frontend 161 tes. ruff/mypy strict/ESLint/tsc bersih, `next build` lulus.
- Migrasi 0009 diuji naik-turun hanya di DB tes; `alembic check` bersih.
- **E2E dengan model lokal** (LOCAL_DEVELOPMENT §7.7): PDF 2 halaman diunggah lewat UI → 5/5
  item benar, injeksi angka ditolak, satu item diterapkan dengan sumber "Halaman 2, baris 3"; chat
  menjawab pertanyaan RAB dengan benar setelah perbaikan prompt dan pemeriksaan, dengan batasan
  model 3B yang dicatat.

Ditemukan dan diperbaiki selama fase ini:

- Pesan PDF terkunci tertelan menjadi "PDF tidak dapat dibaca (UnsupportedFileError)".
- Kolom PDF yang hanya dipisah dua spasi tidak terpisah; indentasi menghasilkan `|` di awal baris.
- Peringatan memakai nomor baris internal, padahal kutipan memakai "Halaman 2, baris 3".
- Kualitas chat qwen2.5:3b dengan sumber JSON (jawaban kosong makna, bahasa Mandarin, klaim
  "sudah diverifikasi" yang salah) → sumber teks berlabel + pemeriksaan deterministik.
- Dua tes formulir RAB (ketik per karakter) melewati batas 5 detik saat seluruh suite frontend
  berjalan paralel di `check.ps1` (lulus bila dijalankan sendiri) → `testTimeout` 15 detik;
  asersinya tidak berubah.

Belum termasuk:

- **Tesseract OCR** belum dipasang (perlu persetujuan pengguna untuk mengunduh; LOCAL_DEVELOPMENT
  §7.6). Jalur OCR teruji dengan OCR tiruan.
- **Streaming jawaban** dan **mode agentic/MCP** (tool dipanggil Hermes sendiri) — tetap ditunda.
- **Retrieval semantik** (embedding/pencarian vektor): pencarian katalog memakai kata kunci.
- Model yang lebih besar (jendela ≥ 64K nyata) untuk kualitas chat yang lebih andal.

### Ringkasan Fase 10 — Hardening dan MVP release

Yang dikerjakan:

- **Data demo yang jelas** (ADR-045): `seed-demo` kini memainkan alur bisnis lengkap lewat API
  publik sebagai pengguna demo per peran — katalog bersumber (terverifikasi/belum), RAB dari harga
  katalog → disetujui → dokumen terbit → versi 2 draft, penawaran 30/40/30 diterima, SPK & BAST
  sebagian terbit, invoice uang muka dibayar separuh, satu RAB di antrean approval, satu draft
  dengan item belum berharga. Proyek demo kini memiliki PPN 11%, lokasi, dan jadwal.
- **Tes penerimaan MVP** (`test_acceptance.py`): 11 langkah master prompt §13 lewat HTTP API —
  login (salah/benar), klien & proyek, RAB, item desimal, total (Rp 25.835.250), pratinjau PDF
  (teks PDF dibaca), ajukan (terkunci), hanya approver yang boleh menyetujui, terbit idempoten,
  versi 2 diubah → snapshot dan hash PDF dokumen terbit tidak berubah.
- **E2E di browser** dengan akun demo: PM membuat klien & proyek lewat form → Estimator membuat RAB
  dan 3 item, total sama persis dengan tes penerimaan, pratinjau PDF 200/`%PDF-`, ajukan → Approver
  menyetujui dari antrean → Finance menerbitkan RAB-2026-0003/V1 → Estimator membuat v2 dan
  menambah item (Rp 66.905.250) → dokumen tetap Rp 25.835.250 dengan hash PDF/XLSX identik.
  Tampilan ponsel (375 px) halaman RAB dan proyek+chat tanpa scroll horizontal.
- **Validasi migrasi**: tes baru menurunkan dan menaikkan setiap revisi satu per satu; salinan
  data pengembangan (225 baris di 22 tabel bisnis) diturunkan dua migrasi lalu dinaikkan lagi →
  tidak ada baris bisnis berubah, tidak ada selisih model vs skema; seed demo dijalankan pada
  database kosong dengan commit sungguhan. Database sementara dihapus setelahnya.
- **Keamanan** (ADR-046, [SECURITY.md](SECURITY.md)): rate limit per pengguna untuk 18 endpoint
  berat (429 + `Retry-After`); CSP JSON API dan CSP halaman; CORP, `Permissions-Policy`, HSTS di
  production; guard production baru (CORS `https://`, cookie Secure); pemindaian secret (tidak ada
  kebocoran); `npm audit` production 0 kerentanan.
- **Perbaikan UI**: angka gaya Indonesia yang tidak ambigu diterima di semua form angka (ADR-047;
  temuan E2E: "18,5" sebelumnya ditolak); kode perancah "Modul belum tersedia"/lencana fase
  dihapus karena semua modul tersedia; petunjuk anggaran proyek diperbarui.
- **Dokumentasi final**: README (status MVP, keamanan, deployment), [DEPLOYMENT.md](DEPLOYMENT.md)
  (checklist konfigurasi, go-live, uji asap, batasan operasional, rollback),
  [SECURITY.md](SECURITY.md), ADR-045–047, panduan data demo, API (batas permintaan berat).

Verifikasi Fase 10:

- Backend 513 tes (termasuk tes penerimaan, alur demo, migrasi per langkah, hardening,
  guard production). Frontend 167 tes. ruff/mypy strict/ESLint/tsc bersih, `next build`
  lulus.
- Ditemukan dan diperbaiki: input desimal koma ditolak (UX); seed memakai observasi harga
  **terakhir** (belum terverifikasi) alih-alih yang terverifikasi; item manual demo tanpa jenis
  sumber harga; dua tes formulir yang timeout saat seluruh suite paralel (`testTimeout` 15 detik).

Belum termasuk / perlu keputusan:

- `pip-audit` belum dijalankan (perlu izin memasang paket); 5 temuan *high* hanya di rantai alat
  lint dev (`braces`), diterima sementara.
- Tesseract OCR belum dipasang.
- E2E browser otomatis (mis. Playwright) belum ada — perlu mengunduh browser; alur MVP diuji
  otomatis di tingkat API dan manual di browser.
- Deployment publik belum dilakukan (lihat DEPLOYMENT.md).

