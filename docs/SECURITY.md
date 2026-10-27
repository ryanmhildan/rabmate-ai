# Tinjauan keamanan (Fase 10, 2026-10-21)

Ringkasan kontrol yang ada, bukti pengujiannya, hasil pemeriksaan Fase 10, dan risiko yang masih
terbuka. Tinjauan ini dilakukan pada mesin pengembangan; belum ada audit pihak ketiga.

## 1. Kontrol dan buktinya

| Area | Kontrol | Bukti (tes otomatis) |
|---|---|---|
| Autentikasi | Argon2id; sesi server-side (token opak, hash di DB, kedaluwarsa & idle timeout); cookie `HttpOnly`, `SameSite=Lax`, `Secure` di production | `test_auth.py` |
| Brute force | Throttle login per email & per IP dari tabel `login_attempts` (bertahan saat restart) | `test_auth.py` |
| CSRF | Token double-submit terikat sesi pada semua metode non-GET + penolakan `Origin` asing | `test_auth.py`, `test_errors.py` |
| Otorisasi | Izin dicek di backend per endpoint; peran → izin (ADR-017) | `test_permissions.py` (matriks), tes API per modul |
| Isolasi organisasi | Filter `organization_id` di setiap query; FK komposit; objek org lain → 404 | `test_isolation.py`, tes isolasi per modul |
| Data uang | Decimal end-to-end, totals dihitung server; snapshot + SHA-256 untuk dokumen terbit | `test_rab_calculation.py`, `test_documents_api.py`, `test_acceptance.py` |
| Idempotensi | Kunci idempotensi untuk penerbitan dan pembayaran | `test_documents_api.py`, `test_billing_api.py` |
| Upload | Batas ukuran (baca terbatas), jenis dari isi file + ekstensi cocok, zip bomb, nama hanya tampilan, isi di DB, unduhan `attachment` + `nosniff` | `test_intake.py`, `test_ai_documents_api.py` |
| Kop surat | PNG/JPEG dari isi byte, maks. 2 MB, piksel dicek sebelum didekode (maks. 25 MP), lalu digambar ulang server sebagai PNG baru tanpa metadata (EXIF, teks, profil); hanya hasil olahan yang disimpan dan ditampilkan; PDF menolak gambar yang SHA-256-nya tidak cocok dengan snapshot | `test_letterhead.py` |
| Isi dokumen | Rumus XLSX tidak dihitung; instruksi di dokumen = data; angka hasil AI dicek ke teks sumber | `test_intake.py`, `test_ai_rules.py`, uji model nyata |
| Ekspor | Teks pengguna selalu ditulis sebagai string, tidak pernah sebagai formula (CSV/XLSX injection); impor tidak menghitung rumus | `test_documents_render.py`, `test_pricing_import.py`, `test_rab_import.py` |
| AI | Hanya Hermes di loopback, toolset diverifikasi (fail closed), tool read-only ber-allowlist dengan izin pengguna, tanpa SQL/shell/file, tanpa fallback cloud, log tanpa isi | `test_ai_adapter.py`, `test_ai_api.py`, `test_ai_documents_api.py` |
| Endpoint berat | Rate limit per pengguna (PDF/XLSX, terbit, unggah/impor, AI) → 429 + `Retry-After` | `test_hardening.py` |
| Header | API: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, COOP, CORP, `Permissions-Policy`, CSP `default-src 'none'` untuk JSON, HSTS di production. Web: CSP `frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'` untuk halaman | `test_health.py`, `test_hardening.py`, dicek di browser |
| Konfigurasi | Production menolak `SECRET_KEY` lemah, CORS `http://`, cookie non-Secure; `HERMES_BASE_URL` wajib loopback; CORS wildcard ditolak | `test_config.py` |
| Error & log | Format error seragam tanpa stack trace; request id; redaksi password/token/URL kredensial | `test_errors.py`, `test_logging.py` |
| Data demo | Hanya `@example.com` & label "(Demo)", ditolak di production, dibuat lewat API publik | `test_cli.py`, `test_demo_story.py` |

## 2. Pemeriksaan yang dijalankan di Fase 10

- **Secret di repository.** 344 berkas yang akan ikut ter-commit dipindai: pola kunci umum (AWS,
  GitHub, private key, `sk-…`) dan **nilai** rahasia dari `.env` lokal (secret key, URL DB, kunci
  Hermes, kata sandi PostgreSQL & demo) dicocokkan tanpa dicetak → **tidak ada yang bocor**.
  `.env`, `var/`, `.venv/`, `node_modules/` terkonfirmasi di-ignore. `.claude/launch.json` hanya
  memuat kunci stub tes (`stub-kunci-lokal`).
- **Dependensi frontend.** `npm audit --omit=dev` → **0 kerentanan** pada dependensi production.
  `npm audit` (termasuk dev) → 5 temuan *high* di rantai alat lint
  (`eslint-config-next → @next/eslint-plugin-next → fast-glob → micromatch → braces`, DoS lewat
  pola glob). Hanya berjalan saat lint di mesin pengembang dengan pola milik repo sendiri;
  perbaikan otomatis menurunkan `eslint-config-next` ke 14 (breaking). **Diterima sementara**,
  pantau rilis `eslint-config-next`.
- **Dependensi backend.** `pip check` → tidak ada konflik. `pip-audit` **belum dijalankan**: belum
  terpasang dan memasangnya berarti mengunduh paket baru (perlu persetujuan). Perintah yang
  disarankan setelah disetujui: `python -m pip install pip-audit` lalu `python -m pip_audit`.
- **Dependensi runtime yang hilang (diperbaiki di Fase 9).** `httpx2` dan `pypdf` dipakai saat
  runtime tetapi hanya tercatat sebagai dependensi dev; instalasi production akan gagal
  mengimpor adapter Hermes. Kini tercatat sebagai dependensi runtime bersama `pillow`.
- **Migrasi.** Setiap revisi turun-naik satu per satu (tes), dan downgrade/upgrade dua migrasi
  terakhir pada salinan data pengembangan tanpa perubahan data bisnis.

## 3. Risiko yang diterima / batasan

- CSP halaman tidak membatasi `script-src`: Next.js memakai skrip inline untuk hidrasi; kebijakan
  berbasis nonce memaksa semua halaman dirender dinamis. Mitigasi: tidak ada
  `dangerouslySetInnerHTML`/`eval` di kode aplikasi, data selalu dirender sebagai teks oleh React.
  Satu-satunya skrip inline milik aplikasi adalah skrip tema (`THEME_BOOT_SCRIPT` di
  `apps/web/src/lib/theme.ts`): teks konstan yang hanya membaca pilihan tema dari `localStorage` dan
  menyetel `data-theme` sebelum render pertama, tanpa data pengguna atau server.
- Rate limit endpoint berat dan kunci model AI ada di memori proses (lihat DEPLOYMENT §6).
- Background task AI hilang bila proses API restart (ditandai `ai_interrupted`).
- Tidak ada MFA, verifikasi email, atau reset kata sandi lewat email.
- Model lokal 3B dapat salah menempatkan kutipan atau mengklaim status; pemeriksaan otomatis
  hanya menandai, pengguna tetap harus memeriksa sumber (ADR-044).
- OCR (Tesseract) belum dipasang; jalurnya diuji dengan OCR tiruan.
