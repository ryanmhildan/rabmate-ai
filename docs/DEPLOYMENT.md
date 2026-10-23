# Checklist deployment RABmate AI

> Status: MVP berjalan dan teruji **lokal**. Belum pernah di-deploy ke server publik; dokumen ini
> adalah daftar periksa untuk saat hal itu diputuskan (perlu persetujuan eksplisit pemilik proyek).

## 1. Bentuk deployment yang disarankan

```
Internet ─HTTPS─> reverse proxy (TLS, HSTS, batas ukuran body, rate limit)
                    └─> Next.js `next start` (:3000, rewrite /api/* ke API)
                          └─> FastAPI/uvicorn (127.0.0.1:8000)
                                ├─> PostgreSQL 17 (jaringan privat)
                                └─> Hermes Agent API server (127.0.0.1:8642) → Ollama (lokal)
```

- Hanya reverse proxy yang terbuka ke internet. API, PostgreSQL, Hermes, dan Ollama bind ke
  loopback/jaringan privat.
- Satu proses API (satu worker uvicorn) dianjurkan untuk MVP: kunci model AI, rate limit endpoint
  berat, dan background task berada di memori proses (lihat §6).

## 2. Konfigurasi wajib (`.env` di server, tidak pernah di repository)

| Variabel | Nilai production | Catatan |
|---|---|---|
| `APP_ENV` | `production` | Mengaktifkan guard di bawah; dokumentasi OpenAPI otomatis mati |
| `SECRET_KEY` | acak ≥ 32 karakter | Ditolak saat start bila placeholder/pendek |
| `CORS_ALLOWED_ORIGINS` | `https://domain-anda` | Wajib `https://` (ditolak saat start bila `http://`); juga dipakai untuk cek `Origin` |
| `SESSION_COOKIE_SECURE` | kosong atau `true` | Default `true` di production; `false` ditolak |
| `TRUSTED_PROXY_IPS` | IP server Next.js | Untuk `X-Forwarded-For` (log, throttle login) |
| `DATABASE_URL` | user DB khusus aplikasi, kata sandi kuat | Bukan superuser; DB terpisah dari pengujian |
| `LOG_JSON` | `true` | Log terstruktur dengan request id; password/token/URL kredensial diredaksi |
| `RATE_LIMIT_EXPENSIVE_PER_MINUTE` | 30 (default) | Per pengguna, per proses (ADR-046) |
| `UPLOAD_MAX_MB` | 10 (default) | Samakan dengan batas body di reverse proxy (+ margin) |
| `AI_ENABLED`, `HERMES_*` | sesuai §5 | `HERMES_BASE_URL` wajib loopback (ditolak bila bukan) |
| `API_INTERNAL_URL` (web, saat build) | `http://127.0.0.1:8000` | Rewrite Next.js diselesaikan saat `next build` |
| `NEXT_TELEMETRY_DISABLED` | `1` | |

`TEST_DATABASE_URL` tidak dipakai di production. Jangan menyalin `.env` pengembangan.

## 3. Sebelum go-live

- [ ] Server dan dependensi: Python 3.12+, Node.js 24+, PostgreSQL 17.
- [ ] Backend: `pip install .` di virtualenv (dependensi runtime saja), lalu
      `alembic upgrade head`.
- [ ] Frontend: `npm ci && npm run build`, jalankan `npm run start`.
- [ ] Organisasi & admin pertama: `python -m app.cli create-admin ...` (tidak ada akun bawaan).
      **Jangan** menjalankan `seed-demo` (ditolak di production).
- [ ] Reverse proxy: TLS, redirect HTTP→HTTPS, HSTS (API juga mengirim HSTS di production), batas
      body ≥ `UPLOAD_MAX_MB`, timeout wajar; rate limit tambahan bila memakai lebih dari satu
      worker.
- [ ] Backup PostgreSQL terjadwal (`pg_dump`) **dan uji restore**. Berkas dokumen terbit dan dokumen
      sumber tersimpan di database, jadi backup database sudah mencakupnya.
- [ ] Pemeriksaan keamanan: `npm audit --omit=dev` (hasil terakhir: 0 kerentanan), `pip-audit`
      (lihat [SECURITY.md](SECURITY.md) — belum dijalankan di mesin pengembangan), tidak ada secret
      di repository.
- [ ] `scripts/check.ps1` lulus pada commit yang akan di-deploy.

## 4. Uji asap setelah deploy

1. `GET /api/v1/health` → `status: ok`, `database: ok` (dan `ai: ok` bila AI aktif).
2. Login admin; buat klien dan proyek; buat RAB dengan dua item.
3. Pratinjau PDF terbuka; ajukan → setujui (akun approver) → terbitkan dokumen; unduh PDF/XLSX.
4. Header respons: `Strict-Transport-Security`, `Content-Security-Policy` pada halaman dan JSON,
   cookie sesi `Secure; HttpOnly`.
5. Log tidak memuat isi dokumen, kata sandi, atau token.

## 5. AI lokal (opsional)

- Hermes Agent dengan `HERMES_HOME` khusus RABmate, API server di `127.0.0.1:8642` dengan kunci
  acak, `platform_toolsets.api_server: []` (tanpa terminal/file/web), telemetri mati.
- Model lokal lewat Ollama di mesin yang sama; tidak ada fallback ke penyedia cloud.
- Model `qwen2.5:3b` hanya layak untuk ekstraksi dengan tinjauan manusia (LOCAL_DEVELOPMENT §7.4,
  §7.7). Untuk chat yang lebih andal gunakan model dengan jendela ≥ 64K yang sebenarnya.
- OCR: pasang Tesseract + data bahasa `ind` bila dokumen hasil scan perlu dibaca (§7.6).
- Fitur non-AI tetap berjalan bila AI mati; `/health` tetap 200 dengan `ai: error`.

## 6. Batasan operasional yang diketahui

- **Background task** (permintaan AI) berjalan di proses API. Bila proses dimulai ulang di tengah
  jalan, run ditandai `ai_interrupted` saat berikutnya dibaca; pengguna mengirim ulang.
- **Rate limit endpoint berat** disimpan di memori per proses. Dengan beberapa worker, batas efektif
  berlipat; pasang rate limit di reverse proxy sebelum menambah worker.
- **Kunci model AI** juga per proses. Satu run aktif per organisasi tetap dijaga database.
- Belum ada reset kata sandi lewat email, MFA, atau notifikasi email; reset kata sandi lewat
  `python -m app.cli set-password` oleh admin server.

## 7. Rollback

- Ambil backup database sebelum `alembic upgrade`.
- Downgrade migrasi hanya setelah membaca efeknya: `0009` menghapus dokumen sumber, percakapan
  chat, dan run AI jenis baru; `0008` menghapus seluruh riwayat run AI. Data bisnis inti (RAB,
  dokumen, penawaran, invoice, pembayaran, SPK/BAST) tidak tersentuh oleh keduanya (diuji pada
  salinan data, lihat PROJECT_PLAN Fase 10).
- Lebih aman: kembalikan kode versi sebelumnya **dan** restore backup database.
