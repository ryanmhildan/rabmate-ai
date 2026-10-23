# Catatan Keputusan Teknis (ADR ringkas)

Format: konteks → keputusan → alasan → konsekuensi. Status: **Diterima**, **Usulan** (belum
diverifikasi), atau **Diganti**.

---

## ADR-001 — Monorepo sederhana tanpa workspace manager
**Status:** Diterima (Fase 0)

Repository kosong saat audit. Struktur: `apps/web` (Next.js), `services/api` (FastAPI), `infra/`,
`docs/`, `scripts/`. Tidak memakai Turborepo/Nx/npm workspaces karena hanya ada satu paket JS.
`packages/shared-types` belum dibuat; tipe frontend dibangkitkan dari OpenAPI bila diperlukan.

## ADR-002 — Integrasi Hermes sebagai adapter di dalam API, bukan service terpisah
**Status:** Diterima (Fase 0)

Adapter berada di `services/api/app/ai/` dengan interface `AgentAdapter` dan implementasi
`HermesAdapter` (HTTP) serta `FakeAgentAdapter` (tes). `services/agent-adapter` tidak dibuat dulu
karena menambah satu proses tanpa manfaat nyata di MVP. Interface dibuat sempit agar mekanisme
integrasi bisa diganti.

## ADR-003 — Mekanisme integrasi Hermes: API server HTTP + MCP tools
**Status:** Diperbarui di Fase 8 — lihat ADR-040 (API server diverifikasi terhadap dokumentasi v0.22.2; mode `structured` dipakai lebih dulu, MCP ditunda)

Sumber: dokumentasi resmi (diakses 2026-10-18)
- API server: <https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server>
- MCP: <https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp>
- Provider lokal: <https://hermes-agent.nousresearch.com/docs/integrations/providers>
- CLI: <https://hermes-agent.nousresearch.com/docs/reference/cli-commands>

Yang terdokumentasi:
- API server OpenAI-compatible (`API_SERVER_ENABLED`, `API_SERVER_KEY` wajib, default
  `127.0.0.1:8642`) dengan `/v1/chat/completions`, `/v1/responses`, Runs API (`/v1/runs`, SSE events,
  stop), `/v1/toolsets`, `/health`.
- MCP client di Hermes (`mcp_servers` di `config.yaml`) dengan `tools.include` / `tools.exclude`,
  `headers`, `timeout`.
- `agent.disabled_toolsets` untuk mematikan toolset bawaan; profil (`--profile`) terpisah.
- One-shot CLI `hermes chat -q … --oneshot --format stream-json` sebagai alternatif.
- **Tidak ditemukan** Python SDK resmi untuk di-embed. Tidak diasumsikan ada.

Keputusan: FastAPI memanggil Hermes API server lewat HTTP (`httpx`), dan Hermes memanggil kembali
tools RABmate yang diekspos sebagai MCP server lokal dengan allowlist. CLI one-shot dicatat sebagai
rencana cadangan jika API server bermasalah di Windows.

## ADR-004 — Profil Hermes khusus `rabmate`, tanpa toolset bawaan
**Status:** Diterima (Fase 8) — dijalankan sebagai `HERMES_HOME` terpisah, dijaga oleh cek `/v1/toolsets` (ADR-040)

Dokumentasi API server menyatakan agent berjalan dengan toolset penuh (termasuk terminal) secara
default. RABmate memakai profil terpisah (`hermes -p rabmate …`) agar konfigurasi global pengguna
tidak diubah, dengan semua toolset bawaan dinonaktifkan dan hanya MCP server RABmate yang aktif.
Konfigurasi aktual diverifikasi lewat `GET /v1/toolsets` sebelum adapter mau mengirim permintaan
(adapter menolak berjalan bila toolset berbahaya terdeteksi).

## ADR-005 — Model lokal: Ollama sebagai runtime awal, tanpa fallback cloud
**Status:** Diterima (Fase 8). Ollama 0.40.6 + Hermes 0.22.2 terpasang dan teruji dengan `qwen2.5:3b`; batasan jendela dicatat di ADR-042

Hermes mensyaratkan konteks **≥ 64.000 token** dan menolak start bila kurang. Ollama perlu
`OLLAMA_CONTEXT_LENGTH=64000` karena default untuk VRAM < 24 GB hanya 4.096. Dengan VRAM 6 GB,
kandidat realistis adalah model 1,5–4B terkuantisasi dengan KV cache terkuantisasi; sebagian
lapisan mungkin di-offload ke RAM. Model yang benar-benar diuji akan dicatat di
`docs/LOCAL_DEVELOPMENT.md`. Konfigurasi model lokal dipisah dari konfigurasi Claude Code. Adapter
tidak pernah beralih ke penyedia cloud secara otomatis; jika model gagal, fitur AI menampilkan
status "tidak tersedia" dan fitur non-AI tetap jalan.

## ADR-006 — Autentikasi: sesi server-side via cookie HttpOnly + CSRF
**Status:** Diterima (implementasi Fase 2)

Next.js me-rewrite `/api/*` ke FastAPI sehingga cookie first-party. Token sesi acak 256-bit,
disimpan di DB sebagai hash SHA-256, cookie `HttpOnly`, `SameSite=Lax`, `Secure` di produksi.
Mutasi wajib header `X-CSRF-Token` (double-submit) dan `Origin` yang diizinkan. Tidak ada token di
`localStorage`. Alasan: revokasi sesi mudah, tidak ada JWT di browser. Password di-hash dengan
Argon2id (`argon2-cffi`).

## ADR-007 — Uang dan kuantitas: `Decimal` + `NUMERIC`
**Status:** Diterima (implementasi Fase 3)

- Nilai uang: `NUMERIC(20, 2)`; harga satuan: `NUMERIC(20, 4)`; kuantitas: `NUMERIC(18, 4)`.
- Python memakai `decimal.Decimal`, tidak ada `float` di jalur uang. Pydantic menerima angka
  sebagai string/Decimal.
- Pembulatan `ROUND_HALF_UP` ke 2 desimal pada subtotal item, diskon, dan pajak; grand total dihitung
  dari nilai yang sudah dibulatkan. Urutan detail ditetapkan & diuji di Fase 3.
- Mata uang default `IDR`. Tampilan Rupiah tanpa desimal bila nilainya bulat.

## ADR-008 — Primary key UUID + nomor dokumen terpisah
**Status:** Diterima

PK `UUID` (v4, dibangkitkan aplikasi) agar ID tidak dapat ditebak di URL. Nomor dokumen manusiawi
(mis. `RAB/2026/0001`) disimpan terpisah dengan unique constraint per organisasi.

## ADR-009 — PostgreSQL via Docker, driver psycopg 3, SQLAlchemy 2.x sinkron
**Status:** Diterima (Fase 1)

`psql` tidak terpasang di host, sehingga PostgreSQL 17 dijalankan via Docker Compose. Driver
`psycopg` (v3, binary). SQLAlchemy memakai API sinkron: FastAPI menjalankan endpoint `def` di
threadpool; ini lebih sederhana untuk transaksi dan tes, dan beban MVP tidak membutuhkan async.
Tes API memakai database PostgreSQL terpisah (`rabmate_test`), bukan SQLite, karena perilaku
`NUMERIC`, enum, dan locking harus sama dengan produksi.

## ADR-010 — Tooling Python: venv + pip, ruff, pytest, mypy
**Status:** Diterima (Fase 1)

`uv` tidak terpasang; dipakai `python -m venv` + `pip install -e ".[dev]"` dari `pyproject.toml`.
Ruff untuk lint/format, pytest untuk tes, mypy untuk pemeriksaan tipe.

## ADR-011 — Frontend: Next.js App Router via `create-next-app`, npm
**Status:** Diterima (Fase 1)

Versi Next.js, React, TypeScript, Tailwind, dan ESLint mengikuti yang dipilih `create-next-app`
versi terpasang (dikunci di `package-lock.json`), bukan dipilih manual, untuk menghindari
kombinasi yang tidak kompatibel (TypeScript 7 sudah rilis sebagai `latest`, tetapi kompatibilitas
tooling Next.js harus mengikuti template resmi). Tes komponen memakai Vitest + Testing Library.
Komponen UI dibuat sendiri di atas Tailwind; library tambahan (tabel, grafik) dievaluasi saat
dibutuhkan.

Hasil aktual (Fase 1): `create-next-app@16.4.2` memilih Next 16.4.2, React 19.3, TypeScript
**5.9.3** (bukan 7), ESLint **9.39** (sudah ditandai *no longer supported* oleh ESLint; dibiarkan
karena itu pilihan template dan `eslint-config-next` belum diuji di sini dengan ESLint 10), Tailwind
4.3 via `@tailwindcss/turbopack`, dengan `cacheComponents` + `partialPrefetching` aktif.
`@types/node` dinaikkan dari `^20` ke `^24` agar sesuai runtime Node 24 dan peer Vitest 5.
Vitest memakai `resolve.tsconfigPaths` bawaan Vite 8 (tanpa plugin tambahan).

## ADR-012 — Background job: belum ada queue
**Status:** Diterima (Fase 1)

Tidak ada Redis/Celery di MVP awal. Jika impor/PDF/ekstraksi butuh asinkron, dipakai tabel `jobs`
di PostgreSQL + worker sederhana dengan status, batas retry, dan kunci idempoten.

## ADR-013 — Fetch data di client: TanStack Query
**Status:** Diterima (Fase 1)

Panduan bawaan Next.js 16.4 merekomendasikan library data-fetching untuk Client Components, dan
aturan lint React Compiler (`react-hooks/set-state-in-effect`) menolak pola fetch di `useEffect`.
Aplikasi ini akan penuh tabel, paginasi, dan mutasi, sehingga TanStack Query dipakai sejak awal.
Retry default hanya untuk error non-4xx (maks. 2 kali); panel status tidak retry.

## ADR-014 — Temuan `npm audit` pada tooling dev diterima sementara
**Status:** Diterima (Fase 1), ditinjau ulang di Fase 10

`npm audit` melaporkan 5 temuan *high* yang semuanya satu rantai: `eslint-config-next →
@next/eslint-plugin-next → fast-glob → micromatch → braces` (DoS stack exhaustion pada pola glob
bersarang). Hanya dipakai saat lint dengan pola dari konfigurasi kita sendiri, tidak ikut ke bundle
produksi (`npm audit --omit=dev` = 0 temuan). Satu-satunya "fix" yang ditawarkan adalah downgrade ke
`eslint-config-next@14`, yang tidak diterima.

## ADR-015 — Host database `127.0.0.1`, bukan `localhost`
**Status:** Diterima (Fase 1)

Terukur di mesin pengembangan: koneksi psycopg ke `localhost` butuh ±8 detik karena Windows
me-resolve `::1` lebih dulu sementara Docker hanya mem-publish port di `127.0.0.1`; ke
`127.0.0.1` 0,04 detik. Tanpa `connect_timeout`, Alembic tertahan tanpa batas. Semua URL default
memakai `127.0.0.1` dan Alembic diberi `connect_timeout`.

## ADR-016 — Tes HTTP backend memakai `httpx2`
**Status:** Diterima (Fase 1)

Starlette 1.8 menandai `httpx` sebagai deprecated untuk `TestClient` dan meminta `httpx2`
(dikelola organisasi Pydantic). Dependensi dev memakai `httpx2`; runtime tidak bergantung padanya.

## ADR-017 — Role tetap di kode, izin berbentuk string
**Status:** Diterima (Fase 2)

Enam role (Owner/Admin, Project Manager, Estimator, Finance, Approver, Viewer) dipetakan ke
himpunan permission di `app/modules/identity/permissions.py`. Endpoint hanya memeriksa permission
(`require(Permission.X)`), tidak pernah nama role. Tabel `roles`/`permissions` di database belum
dibuat karena MVP tidak butuh role kustom; bila kelak dibutuhkan, cukup mengubah cara membership
diterjemahkan menjadi permission. Matriks diuji (`tests/test_permissions.py`). Perubahan role atau
penonaktifan anggota langsung mencabut sesi orang tersebut di organisasi itu.

## ADR-018 — Atribut proyek fleksibel di JSONB terbatas
**Status:** Diterima (Fase 2)

Field umum (klien, jadwal, lokasi, anggaran, pajak) adalah kolom. Atribut khusus jenis proyek
(luas bangunan, material utama, jumlah unit, …) disimpan di `projects.attributes` JSONB dengan
batas: maks. 30 kunci `snake_case`, nilai skalar (string ≤ 500, integer, boolean). Tidak dipakai
untuk data yang dihitung atau dicari; itu tetap menjadi kolom/tabel relasional.

## ADR-019 — Sesi dicek di browser (AuthGate), `instant = false` pada halaman terautentikasi
**Status:** Diterima (Fase 2), ditinjau ulang bila halaman perlu dirender di server

Semua data bisnis diambil di browser dengan sesi pengguna (TanStack Query → `/api/*` rewrite →
FastAPI). `proxy.ts` hanya mengecek keberadaan cookie sesi (redirect cepat ke `/login`);
validitasnya diputuskan API, dan `AuthGate` mengalihkan ke login saat menerima 401. Karena itu
segmen halaman tidak masuk ke static shell, dan Next.js 16.4 (Cache Components) memberi peringatan
pengembangan *instant navigation*. Sesuai panduan resmi "authentication with Cache Components",
halaman di `(app)` mengekspor `instant = false`. Alternatif (membaca sesi di Server Component dan
memanggil FastAPI dari server) ditunda karena menambah jalur kedua ke API tanpa manfaat bagi MVP.

## ADR-020 — Nilai desimal wajib string di API
**Status:** Diterima (Fase 2)

Terbukti saat pengujian: angka JSON `12345678901234567.89` diterima Pydantic sebagai float dan
menjadi `12345678901234568` tanpa error. Tipe `Money`/`Percent` (`app/shared/money.py`) menolak
float dengan pesan yang jelas; integer tetap diterima karena eksak. Frontend selalu mengirim string
dan memformat tampilan dengan `Intl.NumberFormat` dari string (tanpa konversi ke `Number`).

## ADR-021 — Data demo terpisah dan tidak bisa dibuat di production
**Status:** Diterima (Fase 2)

`python -m app.cli seed-demo` membuat organisasi berlabel "(Demo)" dengan satu akun per role
(`demo.<role>@example.com`, domain cadangan RFC 2606). Perintah menolak berjalan bila
`APP_ENV=production` atau bila data demo sudah ada. Kata sandi acak ditulis ke
`var/demo-credentials.txt` (di-.gitignore), tidak dicetak ke terminal.

## ADR-022 — Urutan & pembulatan kalkulasi RAB
**Status:** Diterima (Fase 3)

`subtotal item = round2(kuantitas × harga satuan)`; subtotal RAB = jumlah subtotal item yang
berharga; diskon (persen dari subtotal atau nominal ≤ subtotal) dikurangkan **sebelum** pajak
(DPP = subtotal − diskon); pajak = round2(DPP × tarif / 100) dan **hanya** bila label + tarif
diisi; grand total = DPP + pajak. round2 = `ROUND_HALF_UP` ke 2 desimal (bukan banker's rounding),
diterapkan per baris lalu dijumlah. Perhitungan memakai konteks `Decimal` 60 digit sehingga hasil
di luar batas `NUMERIC(20,2)` terdeteksi sebagai overflow alih-alih dibulatkan diam-diam.
Satu modul murni (`calculation.py`) adalah satu-satunya tempat rumus; frontend hanya menampilkan
hasil server dan tidak menghitung ulang. Item tanpa harga boleh ada di draft tetapi tidak dihitung
dan memblokir pengajuan.

## ADR-023 — Status per versi; versi disetujui immutable
**Status:** Diterima (Fase 3)

Status melekat pada `rab_versions`, bukan pada dokumen RAB. Hanya versi `draft` yang dapat diubah.
Merevisi versi yang disetujui/ditolak/diarsipkan = membuat versi baru yang menyalin item dan
pengaturan. Saat versi baru disetujui, versi yang sebelumnya disetujui menjadi `archived` dengan
catatan `superseded`, sehingga selalu ada paling banyak satu versi disetujui per RAB. Paling banyak
satu versi terbuka (`draft`/`in_review`) per RAB, dijaga di service dan oleh unique index parsial.
Persetujuan oleh diri sendiri diperbolehkan (perusahaan kecil sering hanya punya satu Owner) dan
tetap tercatat; pemisahan tugas wajib dapat ditambahkan sebagai pengaturan organisasi nanti.

## ADR-024 — Konkurensi RAB: row lock + optimistic version
**Status:** Diterima (Fase 3)

Setiap mutasi item/header/status mengunci baris `rab_versions` (`SELECT … FOR UPDATE OF
rab_versions`) sehingga perhitungan total dan transisi status berurutan; transisi dan pembuatan
versi juga mengunci baris `rab_documents`. Klien mengirim `lock_version` (header) atau `row_version`
(item) yang terakhir dibaca; ketidaksesuaian → 409 `version_conflict`. Konflik per item (bukan per
versi) agar dua estimator dapat mengedit item berbeda bersamaan.

## ADR-025 — Harga katalog = riwayat observasi append-only + status verifikasi
**Status:** Diterima (Fase 4)

Item katalog (`price_catalog_items`) tidak menyimpan harga. Setiap harga adalah baris
`price_observations` yang tidak pernah diubah atau ditimpa: harga baru = baris baru, sehingga riwayat
dan provenance (supplier, referensi, URL, tanggal, masa berlaku, lokasi, spesifikasi menurut sumber,
asal impor) selalu utuh. Satu-satunya perubahan yang diizinkan adalah status verifikasi:
`unverified → verified | rejected` dan `verified → rejected` (tidak bisa kembali ke `unverified`;
harga yang ditolak tidak dapat diverifikasi ulang — catat harga baru). Verifikasi butuh izin
`pricing.verify` (Owner, Approver); menolak wajib alasan. Harga tanpa supplier, referensi, maupun URL
**tidak dapat** diverifikasi (422 di service dan CHECK `verified_requires_source` di DB). Semua harga
baru — manual, impor, maupun eksternal — mulai sebagai `unverified`. Satuan observasi selalu satuan
item; satuan item terkunci setelah ada riwayat harga. Tidak ada konversi satuan otomatis.

## ADR-026 — Pencarian kandidat harga: skor deterministik yang dapat dijelaskan
**Status:** Diterima (Fase 4)

`GET /price-catalog/candidates` menggabungkan item katalog (trigram `pg_trgm` + token) dan item RAB
yang **disetujui** sebagai kandidat, lalu menilai dengan aturan murni di `pricing/matching.py`:
60·Jaccard token nama + 20·kemiripan urutan + 10 bila angka ukuran sama (`Cat6` = `Cat 6`) + 10·
kecocokan spesifikasi. Batas: satuan berbeda → level `low` dan `unit_compatible=false` (UI tidak
mengizinkan memakai), ukuran/angka hilang atau merek berbeda → maksimal `medium`. Level: `high` ≥ 75,
`medium` ≥ 45. Setiap kandidat membawa `reasons` dan `warnings` (belum terverifikasi, lebih dari 180
hari, lokasi pasar berbeda) yang ditampilkan apa adanya. Untuk item katalog dipakai harga
terverifikasi terbaru, atau harga terbaru bila belum ada yang terverifikasi (dengan peringatan).
Tidak ada model AI dalam penilaian ini; hasilnya dapat diuji dan dijelaskan.

## ADR-027 — Impor spreadsheet: pratinjau dulu, rumus ditolak, angka ambigu ditolak
**Status:** Diterima (Fase 4)

Impor katalog berjalan dua langkah: unggah → pratinjau tersimpan (`import_jobs`, status `previewed`)
yang memuat hasil per baris (valid/kesalahan, aksi `create_item`/`add_price`), lalu `commit` atau
`discard` eksplisit. `commit` idempoten (job yang sudah tersimpan tidak diproses ulang) dan
mencocokkan ulang baris saat commit. Aturan berkas: `.xlsx` atau `.csv` (dicek dari magic bytes,
bukan hanya ekstensi), maks. 5 MB dan 5.000 baris; openpyxl `read_only`, `data_only=False`, dan sel
berisi rumus **ditolak** — RABmate tidak pernah mengevaluasi rumus atau makro dari berkas pengguna.
Angka berformat ribuan-titik yang ambigu (`4.500`) ditolak, bukan ditebak; `4500`, `4500,75`,
`4.500,75` diterima. Baris impor menjadi observasi `source_type=import`, `unverified`, dengan
referensi `Impor <nama berkas> baris N`. Nama berkas disanitasi. Aturan ambiguitas yang sama
diterapkan di form frontend untuk harga dan kuantitas (`95.000` ditolak dengan petunjuk).

## ADR-028 — Pencarian harga eksternal: tidak dikonfigurasi = jujur tidak tersedia
**Status:** Diterima (Fase 4)

Antarmuka `ExternalPriceProvider` disiapkan, tetapi belum ada penyedia. `PRICE_SEARCH_PROVIDER=none`
(default dan satu-satunya nilai saat ini) membuat `GET /price-sources/external` melaporkan
`configured=false` dan `POST /price-sources/external/search` mengembalikan 503
`external_search_not_configured`. Aplikasi tidak pernah mengarang hasil pencarian atau harga pasar.
Penyedia nanti hanya boleh menghasilkan **kandidat** yang dicatat sebagai observasi
`external` + `unverified` dengan URL sumber, tidak pernah langsung mengubah harga RAB.

## ADR-029 — Tautan harga katalog di item RAB diselesaikan di server
**Status:** Diterima (Fase 4)

Item RAB dapat menyimpan `price_observation_id` (FK komposit, organisasi sama). Bila diisi, server
mengambil harga satuan dari observasi tersebut dan menulis `price_source_type=catalog` serta teks
provenance (`Katalog: KODE nama · supplier · referensi · tanggal · status`); nilai `unit_price`/
`price_source` dari klien diabaikan. Ditolak bila observasi berstatus `rejected`, satuannya berbeda
dengan satuan item, atau mata uangnya berbeda dengan RAB. Harga yang dipakai disalin ke item, sehingga
RAB yang disetujui tidak berubah ketika katalog berubah; status verifikasi saat ini tetap
ditampilkan (`price_verification_status`) dan harga belum terverifikasi menjadi peringatan validasi
`unverified_catalog_price` (tidak memblokir pengajuan — keputusan ada pada approver). Kandidat dari
riwayat RAB disetujui disalin sebagai `price_source_type=history` tanpa tautan.

## ADR-030 — Penerbitan dokumen RAB: hanya versi disetujui, idempoten, satu dokumen berlaku
**Status:** Diterima (Fase 5)

Dokumen resmi hanya diterbitkan dari versi RAB berstatus `approved` (izin `documents.issue`:
Owner, Finance, Approver). Selama penerbitan, baris versi dikunci (`FOR UPDATE`). Dua lapis
pengaman duplikasi: (1) header `Idempotency-Key` — retry dengan kunci yang sama mengembalikan
dokumen yang sama (200, `Idempotent-Replayed: true`), kunci yang dipakai untuk versi lain → 422
`idempotency_key_reused`, unik per organisasi di DB; (2) paling banyak satu dokumen `issued` per
versi (unique index parsial) — permintaan lain tanpa kunci yang cocok → 409 `already_issued` berisi
`document_id`. Nomor dokumen = `<nomor RAB>/V<versi>`, dan `-R<n>` untuk penerbitan ulang setelah
pembatalan; unik per organisasi. Dokumen terbit tidak dapat diubah; hanya dapat dibatalkan (`void`)
dengan alasan wajib, tercatat di audit. Berkas dokumen yang dibatalkan tetap tersedia apa adanya
sebagai arsip (status ditampilkan di aplikasi).

## ADR-031 — Snapshot + berkas dirender sekali dan disimpan di PostgreSQL
**Status:** Diterima (Fase 5)

Saat terbit, data dibekukan menjadi snapshot JSON (`documents.snapshot`, berskema versi
`schema_version`): identitas perusahaan, klien, proyek, item, total, persetujuan, pengaturan
template, bahkan label tampilan. Hash SHA-256 snapshot kanonik (kunci terurut) disimpan dan
16 karakter pertamanya dicetak di kaki PDF sebagai kode verifikasi. PDF dan XLSX dirender **sekali**
dari snapshot di dalam transaksi penerbitan dan disimpan sebagai `bytea` di `document_files`
(beserta SHA-256 dan ukuran, maks. 20 MB per berkas; dimuat hanya saat diunduh). Unduhan selalu
menyajikan byte tersimpan, bukan render ulang, sehingga perubahan RAB, profil perusahaan, template,
maupun kode renderer di masa depan tidak mengubah dokumen terbit. Disimpan di database (bukan
`var/storage`) agar berkas atomik dengan penerbitan dan ikut backup; upload pengguna (Fase 9) tetap
direncanakan di penyimpanan berkas. Sebelum snapshot dibuat, total versi dihitung ulang dengan modul
kalkulasi; jika tidak sama dengan total tersimpan, penerbitan/pratinjau ditolak (409).

## ADR-032 — Renderer: ReportLab (PDF) dan openpyxl (XLSX), deterministik dan aman
**Status:** Diterima (Fase 5)

PDF memakai ReportLab 5 (BSD) dengan font Bitstream Vera yang dibundel ReportLab (di-embed, punya
peta ToUnicode; mencakup Latin-1 serta — · × ≤ €; glyph di luar cakupan tampil kosong — font lain
dapat ditambahkan nanti). `rl_config.invariant` membuat keluaran deterministik (snapshot sama → byte
sama). Semua teks pengguna di-escape sebelum masuk `Paragraph`, karena markup ReportLab dapat membaca
berkas lokal (`<img src>`) — diuji. Tanda tangan tidak pernah digambar: blok persetujuan hanya memuat
nama dan tanggal dari catatan persetujuan. XLSX hanya berisi nilai (tanpa rumus); angka ditulis
sebagai angka hanya jika dapat diwakili tepat oleh double, selain itu sebagai teks; teks pengguna
yang tampak seperti rumus (`= + - @`, tab, CR) disimpan sebagai string dengan `quotePrefix`. WeasyPrint
tidak dipilih karena butuh GTK/Pango di Windows. Pratinjau memakai builder snapshot yang sama dengan
penerbitan, ditambah watermark/banner "PRATINJAU" dan tanpa nomor.

## ADR-033 — Impor item RAB: pratinjau → commit, hanya ke versi draft, tambah di akhir
**Status:** Diterima (Fase 5)

Memakai pembaca spreadsheet bersama (`app/shared/spreadsheet.py`, dipakai juga impor katalog):
.csv/.xlsx dicek magic bytes, ≤ 5 MB, ≤ 5.000 baris, rumus ditolak, angka ambigu (`4.500`) ditolak.
Kolom wajib `nama`, `volume`, `satuan`; harga satuan opsional (item tanpa harga tetap masuk tetapi
memblokir pengajuan). Subtotal di pratinjau berasal dari modul kalkulasi. Commit mengunci versi,
mensyaratkan status `draft`, menambahkan item di akhir (item lama tidak diubah), menghitung ulang
total, idempoten, dan diaudit (`rab_item.import`). Item berharga mendapat `price_source_type=import`
dan sumber dari berkas atau "Impor <berkas> baris N". Job impor terikat ke versi dan jenisnya —
endpoint katalog tidak dapat membaca job item RAB dan sebaliknya.

## ADR-034 — Template dokumen per organisasi tanpa data karangan
**Status:** Diterima (Fase 5)

`document_settings` (satu baris per organisasi, `version` optimistik, ubah dengan `org.update`)
menyimpan tagline, warna aksen, teks kaki, ketentuan RAB, opsi kolom (kode item, sumber harga →
halaman mendatar, terbilang), dan informasi pembayaran untuk invoice Fase 6. Identitas perusahaan
diambil dari profil organisasi; kolom kosong tidak dicetak. Ketentuan hanya berasal dari pengguna —
aplikasi tidak menambahkan klausul hukum. Tanpa baris tersimpan, nilai default dipakai (`version`
0). Logo belum didukung (menunggu modul unggah berkas).

## ADR-035 — Termin pembayaran: persen atau nilai tetap sebelum pajak, sisa pembulatan ke termin terakhir
**Status:** Diterima (Fase 6)

Jadwal pembayaran melekat pada penawaran (nilai kontrak = nilai RAB disetujui yang disalin ke
penawaran). Setiap termin berbasis **persen** atau **nilai tetap**, keduanya atas nilai sebelum
pajak (DPP); proyek tidak diasumsikan selalu memakai persen. Aturan (`billing/terms.py`, murni,
Decimal): persen 0 < p ≤ 100 dua desimal; jadwal yang semuanya persen wajib berjumlah tepat 100%
dan termin terakhir menyerap sisa sen; jadwal dengan nilai tetap wajib berjumlah tepat sama dengan
DPP — tanpa penyesuaian diam-diam; pajak dibagi proporsional (round2) dengan sisa ke termin
terakhir, sehingga total semua termin = total penawaran sampai sen. Invoice termin menyalin angka
termin apa adanya, sehingga jumlah invoice = nilai snapshot penawaran.

## ADR-036 — Pembayaran hanya dari catatan sah; alokasi dengan penguncian
**Status:** Diterima (Fase 6)

Status lunas/sebagian/belum dibayar dan "lewat jatuh tempo" (tanggal Asia/Jakarta) diturunkan dari
`invoices.amount_paid`, yang hanya berubah oleh pembayaran tercatat (izin `finance.write`, metode,
referensi, tanggal ≤ hari ini) — tidak pernah dari klaim pengguna atau AI. Pembayaran
dialokasikan ke invoice **terbit** milik klien dan mata uang yang sama, tidak melebihi sisa tagihan;
satu pembayaran boleh dibagi ke beberapa invoice dan sisanya boleh belum dialokasikan (dapat
dialokasikan kemudian). Invoice dikunci dalam urutan id (hindari deadlock) dan CHECK
`amount_paid ≤ grand_total` menjaga konsistensi. Pembayaran tidak diubah/dihapus; kesalahan
dibatalkan dengan alasan sehingga alokasinya dilepas. Pencatatan menerima `Idempotency-Key`
(kunci sama + nilai berbeda → 422).

## ADR-037 — Alur review penawaran & invoice, izin `documents.approve`, nomor invoice saat terbit
**Status:** Diterima (Fase 6)

Penawaran dan invoice memakai alur yang sama: draft → review → disetujui/ditolak → terbit → batal
(`billing/workflow.py`; dibuka kembali ke draft dari ditolak/disetujui-belum-terbit). Penyusun
(penawaran: `rab.write`; invoice: `finance.write`) mengajukan; persetujuan memakai izin baru
`documents.approve` (Owner, Approver) sehingga terpisah dari penyusunan; penerbitan dan pembatalan
memakai `documents.issue`. Penerbitan memakai mekanisme Fase 5 (snapshot, PDF tersimpan,
idempoten). Penawaran bernomor `PNW-YYYY-NNNN` saat dibuat; invoice bernomor `INV-YYYY-NNNN`
**saat terbit** (draft yang dihapus tidak meninggalkan celah nomor). Invoice termin hanya dari
penawaran terbit yang dicatat **diterima klien**, maksimal satu invoice aktif per termin (unique index
parsial). Penawaran/invoice tidak dapat dibatalkan bila masih ada invoice/pembayaran yang
bergantung. Tanggapan klien dicatat manual oleh pengguna (bukan diasumsikan).

## ADR-038 — SPK dari penawaran yang diterima klien; para pihak dan klausul hanya dari pengguna
**Status:** Diterima (Fase 7)

SPK (`spk_documents`) hanya dibuat dari penawaran **terbit** yang dicatat **diterima klien**, maksimal
satu SPK aktif per penawaran (unique index parsial; penawaran dikunci saat pembuatan). Nilai kontrak,
mata uang, dan jadwal termin **disalin/diambil dari penawaran** dan tidak dapat diubah di SPK; snapshot
memeriksa ulang nilai kontrak = total penawaran dan jumlah termin = total. Lingkup pekerjaan
diisi dari penawaran, ketentuan dari template `spk_terms`, lokasi/periode dari proyek — semuanya
dapat diubah selama draft. Sebelum diajukan wajib: tanggal mulai, lingkup, dan **nama penanda tangan
kedua pihak yang diketik pengguna**; PDF hanya mencetak nama/jabatan di bawah ruang tanda tangan
kosong (tidak ada tanda tangan, stempel, atau klausul hukum yang dibuat aplikasi). Alur review sama
dengan ADR-037 (`documents.approve` untuk menyetujui, `documents.issue` untuk terbit/batal);
penyusunan memakai `projects.write` (Owner, Project Manager) karena SPK/BAST adalah dokumen
pelaksanaan. Nomor `SPK-YYYY-NNNN` dan tanggal SPK diberikan **saat terbit**. Selama SPK aktif,
penawaran tidak dapat dibatalkan dan tanggapan klien tidak dapat diubah; SPK tidak dapat dibatalkan
selama masih ada BAST yang belum dibatalkan.

## ADR-039 — BAST mencatat yang benar-benar diserahkan; volume kumulatif ≤ kontrak
**Status:** Diterima (Fase 7)

BAST (`bast_documents` + `bast_items`) dibuat dari SPK terbit, berjenis **sebagian** atau **akhir**
(maksimal satu BAST akhir aktif per SPK, unique index parsial). Baris dapat merujuk item kontrak
(item versi RAB yang menjadi dasar penawaran, imutabel karena versi disetujui) atau berupa
pekerjaan/barang di luar rincian kontrak. Untuk baris kontrak: satuan harus sama dengan kontrak,
satu item kontrak sekali per BAST, dan **volume BAST terbit lain + BAST ini ≤ volume kontrak**.
Aturan diperiksa saat simpan, ajukan, dan **ulang saat terbit sambil mengunci baris SPK**, sehingga
dua BAST yang masing-masing muat tidak dapat sama-sama terbit melebihi kontrak. "Diserahkan" hanya
menghitung BAST terbit; draft/review/disetujui ditampilkan sebagai "dalam proses". Pengisian otomatis
sisa volume hanya opsi titik awal yang harus diperiksa pengguna. Sebelum diajukan wajib tanggal serah
terima (≤ hari ini, Asia/Jakarta), nama pihak yang menyerahkan dan menerima, dan minimal satu baris.
Kondisi barang hanya dari isian pengguna; template tidak menambahkan "dalam keadaan baik" atau
kondisi serah terima lain. Nomor `BAST-YYYY-NNNN` saat terbit; BAST tidak memuat nilai uang (total
dokumen 0). Pembatalan BAST terbit melepaskan volumenya.

## ADR-040 — Adapter Hermes: API server lokal, toolset diverifikasi, tanpa fallback
**Status:** Diterima (Fase 8)

Diverifikasi terhadap dokumentasi resmi Hermes Agent v0.22.2 (rilis 15 Okt 2026, diakses
2026-10-19). Yang dipakai:

- `GET /health` (tanpa auth).
- `GET /v1/toolsets` dan `POST /v1/chat/completions` dengan `Authorization: Bearer <API_SERVER_KEY>`.
  API server bind `127.0.0.1:8642` secara default.

Dokumentasi menyatakan permintaan API server berjalan dengan **toolset penuh** (terminal, file, web,
memory) dan tidak menyediakan parameter per-permintaan untuk membatasinya. Karena itu
`HermesAdapter` (`app/ai/hermes.py`):

- **Hanya lokal.** Menolak `HERMES_BASE_URL` yang bukan loopback; divalidasi saat start.
  Mengabaikan proxy sistem (`trust_env=False`) dan tidak mengikuti redirect.
- **Toolset dicek tiap permintaan.** Sebelum **setiap** permintaan, adapter membaca
  `/v1/toolsets` dan menolak bila ada toolset aktif di luar `HERMES_ALLOWED_TOOLSETS` (default
  kosong). Respons yang tidak bisa diverifikasi (404, format asing, entri tanpa flag) dianggap
  tidak aman (fail closed).
- **Batas eksplisit.** Timeout per permintaan. Retry maksimal `AI_MAX_RETRIES` (default 1) hanya
  untuk gangguan koneksi atau 429/502/503/504; timeout tidak di-retry. Ukuran jawaban dibatasi.
- **Tanpa fallback.** Tidak ada penyedia lain yang bisa dipakai sebagai cadangan.
- **Log tanpa isi.** Log hanya berisi kode status, durasi, dan nama kelas error — tidak pernah
  prompt atau isi jawaban.

`/health` melaporkan AI sebagai `disabled`/`ok`/`error`. Status AI tidak pernah membuat API
"degraded", sehingga fitur non-AI tetap berjalan. Probe di-cache 30 detik.

Batasan yang diakui: adapter tidak dapat memverifikasi provider model di dalam profil Hermes.
Konfigurasi profil RABmate (`HERMES_HOME` terpisah, provider Ollama lokal) didokumentasikan di
LOCAL_DEVELOPMENT §7.

Mode `agentic` (Hermes memanggil tool RABmate via MCP) ditunda. Alasannya:

- Dokumentasi MCP tidak menyediakan konteks per sesi (hanya header statis/`identity_header`).
- Model kecil di 6 GB VRAM tidak andal untuk alur agen multi-langkah.

## ADR-041 — Asisten AI: mode structured, tool read-only ber-allowlist, draft ditinjau manusia
**Status:** Diterima (Fase 8)

Permintaan AI disimpan sebagai `ai_runs` dan diproses di latar belakang (FastAPI
`BackgroundTasks`). Run berstatus queued → running → succeeded/failed → applied/discarded, dan
menyimpan input, `context` (data yang dikirim ke model), hasil tervalidasi, serta error yang aman
ditampilkan.

Batas pemrosesan:

- Satu run aktif per organisasi (unique index parsial), ditambah satu kunci global per proses
  karena GPU lokal melayani satu generasi pada satu waktu.
- Run yang macet melewati batas waktu ditandai `ai_interrupted` saat dibaca.
- Permintaan ditolak di awal (503) bila AI nonaktif, tidak tersedia, atau tidak aman.

**Tool registry.** Data bisnis untuk model hanya diambil lewat registry tool
(`assistant/tools.py`):

- Skema input Pydantic menolak field tak dikenal.
- Izin dicek terhadap izin pengguna sendiri.
- Ada allowlist per workflow.
- Log hanya mencatat nama, hasil, dan durasi.
- **Semua tool read-only** (`get_project_details`, `get_rab_version`). AI tidak punya tool untuk
  menulis, menyetujui, menerbitkan, SQL, shell, atau file.

**Workflow.**

- **`rab_draft`** — model mengusulkan item **tanpa harga**. Volume hanya diterima bila teksnya
  ada di deskripsi.
- **`extract_items`** — teks dokumen bernomor baris, diperlakukan sebagai data tidak tepercaya di
  pesan pengguna, terpisah dari instruksi. Model wajib menyalin angka apa adanya. Kode lalu:
  - memverifikasi angka itu ada di teks (di baris yang dirujuk);
  - mem-parse sesuai format angka yang dipilih pengguna (Indonesia/Inggris);
  - menandai selisih volume × harga ≠ jumlah tertulis tanpa mengoreksi;
  - menjadikan yang gagal "belum diketahui".

Jawaban yang bukan JSON valid mendapat satu kali permintaan perbaikan, lalu gagal dengan rapi.

**Penerapan.** Item masuk ke RAB hanya lewat `apply` oleh pengguna (`ai.use` + `rab.write`):

- Versi harus draft; penguncian versi lalu run, sama seperti mutasi item lain.
- Harga hanya dari katalog (`resolve_for_rab` di server) atau harga tertulis di dokumen (sumber
  `import`, ditandai "diekstrak AI lokal, belum diverifikasi", satuan harus sama).
- Total dihitung ulang oleh mesin RAB.
- Penerapan ulang idempoten.

Izin baru `ai.use` diberikan ke Owner, Project Manager, dan Estimator — peran yang menyusun RAB.

## ADR-042 — `qwen2.5:3b` dengan jendela 32K yang dinyatakan 64K ke Hermes (keputusan pengguna)
**Status:** Diterima (2026-10-20), dengan batasan

Hermes 0.22.2 mensyaratkan jendela ≥ 64.000 token. `qwen2.5:3b` maksimal 32.768. Pengguna memilih
tetap memakai model ini dengan menyetel `model.ollama_num_ctx: 64000` di profil RABmate. Angka itu
lebih besar dari jendela yang sebenarnya, sehingga melewati syarat Hermes.

Model dilayani lewat varian lokal `rabmate-qwen2.5-3b-32k` (Modelfile `num_ctx 32768`,
`temperature 0`). Lewat API OpenAI-compatible, Ollama sebenarnya hanya melayani 4.096 token, dan
Hermes tidak meneruskan `temperature`.

Batasannya:

- Hanya aman untuk permintaan RABmate yang satu giliran, tanpa tool, dengan input dibatasi
  `AI_MAX_INPUT_CHARS` (default 20.000; jangan di atas ±60.000).
- Bukan untuk alur agen panjang.

Uji nyata menunjukkan model ini layak untuk ekstraksi tabel dengan tinjauan manusia, tetapi lemah
untuk menyusun draft dari deskripsi. Pengaman deterministik ADR-041 diperkuat dari temuan uji:

- angka dicocokkan sebagai angka utuh;
- angka di luar baris item ditolak;
- nomor baris dikoreksi lewat nama item;
- teks angka diambil dari dokumen;
- baris ganda digabung.

Mengganti ke model ber-jendela ≥ 64K yang sebenarnya cukup dengan mengubah profil Hermes (dan
menghapus pernyataan `ollama_num_ctx`), tanpa mengubah kode RABmate.

## ADR-043 — Dokumen sumber: unggah aman, dibaca sekali, ekstraksi per bagian, OCR opsional
**Status:** Diterima (Fase 9)

Penawaran vendor, BoQ, dan daftar harga diunggah ke **proyek** sebagai dokumen sumber
(`source_documents`), lalu dibaca oleh workflow `extract_document`.

**Unggahan.**

- Dibaca dengan batas `UPLOAD_MAX_MB` (default 10 MB); lebih besar → 413 tanpa memuat sisanya.
- Jenis ditentukan dari **isi file** (tanda tangan PDF/PNG/JPEG, struktur ZIP XLSX, teks untuk
  CSV/TXT), dan ekstensi harus cocok. File yang menyamar (mis. program berekstensi `.pdf`) ditolak.
- XLSX yang mengembang > 100 MB saat diekstrak ditolak (zip bomb).
- Nama file hanya nama tampilan (segmen terakhir, tanpa karakter kontrol), tidak pernah dipakai
  sebagai path.
- Isi disimpan di PostgreSQL (`bytea`, seperti berkas dokumen di ADR-031) per proyek. File yang
  sama (SHA-256) di proyek yang sama tidak disimpan dua kali.
- Unduhan selalu `attachment`, `nosniff`, `no-store`. Upload perlu `ai.use` + `rab.write`;
  daftar/unduh perlu `rab.read`.

**Pembacaan** (sekali, di latar belakang, hasilnya di-cache di `source_documents.extraction`):

- **PDF:** lapisan teks pypdf mode *layout*; jarak dua spasi atau lebih antarkolom menjadi `" | "`.
  Halaman tanpa teks tetapi bergambar dianggap hasil scan → OCR bila tersedia, bila tidak dilewati
  dengan peringatan. PDF terkunci sandi ditolak dengan pesan jelas.
- **XLSX:** nilai setiap sel, semua sheet. **Rumus tidak pernah dihitung** (ditulis `(rumus)`);
  angka ditulis dalam notasi Indonesia, sehingga format angka XLSX selalu `id`.
- **CSV/TXT:** apa adanya (pemisah dideteksi).
- **PNG/JPEG:** hanya lewat OCR.
- Batas: `INTAKE_MAX_PAGES` (50) halaman, 10 sheet, 3.000 baris per sheet, 300.000 karakter,
  gambar 40 megapiksel, `OCR_MAX_PAGES` (20) halaman OCR, `OCR_TIMEOUT_SECONDS` per halaman.

**OCR.** Tesseract CLI bila terpasang (`TESSERACT_CMD`, `PATH`, atau lokasi bawaan Windows),
dijalankan sebagai perintah tetap tanpa shell pada file sementara yang langsung dihapus, bahasa
`OCR_LANGUAGES` (`ind+eng`). Bila tidak ada, status "OCR tidak tersedia" ditampilkan apa adanya
di UI dan `/ai/status`; PDF digital, XLSX, dan CSV tetap diproses. Tesseract **belum dipasang** di
mesin ini (memasangnya berarti mengunduh installer — perlu persetujuan pengguna).

**Ekstraksi per bagian.**

- Baris dinomori berlanjut lintas halaman (`[n]`, yang dikutip model), dan setiap baris tahu
  lokasinya untuk manusia (`Halaman 2, baris 3`; `Sheet RAB, baris 7`).
- Dokumen dibagi menjadi bagian ≤ `AI_CHUNK_CHARS` (12.000) karakter, maksimal `AI_MAX_CHUNKS`
  (6). Kepala tabel terakhir dibawa (tanpa nomor) ke bagian berikutnya. Baris yang melebihi batas
  dilaporkan, bukan diam-diam dibuang.
- Setiap bagian satu panggilan model (+ perbaikan format) dan melewati aturan deterministik
  ADR-041/042 terhadap baris bagian itu sendiri. Bagian yang jawabannya tetap rusak menjadi
  peringatan; bagian lain tetap dipakai.
- Peringatan memakai lokasi untuk manusia ("dikoreksi ke Halaman 2, baris 3"), bukan nomor
  internal.
- Dokumen harus milik proyek RAB yang sama (dibaca lewat tool `get_source_document`).

**Penerapan.** Harga dokumen bersumber `import` dengan teks "Dokumen 'penawaran.pdf', Halaman 2,
baris 3 — diekstrak AI lokal, belum diverifikasi". Catatan setiap item menyimpan rujukan sumbernya,
termasuk item tanpa harga.

Alternatif yang tidak dipilih: menyimpan di filesystem (dua tempat untuk backup; berkas kecil),
OCR lewat model visi (tidak tersedia di model lokal 3B dan rawan mengarang angka), menghitung
rumus XLSX (bisa dimanipulasi; nilai tersimpan pun tidak selalu ada).

## ADR-044 — Chat proyek: sumber bernomor, retrieval terkendali, jawaban diperiksa kode
**Status:** Diterima (Fase 9)

Pengguna bertanya tentang proyek yang sedang dibuka. Percakapan (`ai_conversations`,
`ai_messages`) **privat milik pembuatnya**: pengguna lain di organisasi yang sama mendapat 404.
Perlu `ai.use` + `projects.read`.

**Pemrosesan.** Setiap pertanyaan menjadi run `chat_answer` (aturan run ADR-041: satu run aktif per
organisasi, kunci model global, kedaluwarsa bila macet, ditolak di awal bila AI tidak siap). UI
mem-polling status. **Streaming ditunda**: jawaban model lokal datang dalam 2–15 detik, dan
pemeriksaan di bawah butuh jawaban utuh sebelum ditampilkan.

**Retrieval** dilakukan backend (bukan model) lewat registry tool read-only ber-allowlist, dengan
izin si penanya:

| Tool | Izin | Isi |
|---|---|---|
| `get_project_details` | `projects.read` | Data proyek |
| `get_project_rabs` | `rab.read` | 3 RAB terbaru, versi terakhir: total, item (maks. 60) dengan harga & sumber harga, daftar item belum berharga |
| `search_catalog` | `pricing.read` | Kata kunci dari pertanyaan → maks. 8 item katalog; harga terverifikasi terbaru, atau terbaru yang tidak ditolak, beserta statusnya |
| `get_project_documents` | `projects.read` | SPK & BAST; penawaran hanya dengan `rab.read`; invoice + jumlah terbayar (dari catatan pembayaran) hanya dengan `finance.read` |

Setiap potongan data menjadi sumber bernomor `[S1]`, `[S2]`, …. Data yang tidak disertakan
(izin, tidak ada yang cocok) dicatat dan ditampilkan sebagai "tidak termasuk". Konteks dibatasi
±16.000 karakter (item RAB dikurangi lebih dulu, dengan catatan). Sumber disajikan ke model sebagai
**teks berlabel**, bukan JSON bertingkat — `qwen2.5:3b` mengikutinya jauh lebih baik. Riwayat: 6
pesan terakhir, tanpa penanda kutipan lama.

**Pemeriksaan deterministik jawaban:**

- Harus berbahasa Indonesia dan substantif (bukan hanya kutipan); bila tidak, model diminta
  memperbaiki.
- Kutipan ke sumber yang tidak ada dihapus, dengan peringatan.
- Angka (≥ 100) yang tidak ada di sumber mana pun → peringatan "bisa hasil hitungan atau karangan
  AI".
- Angka yang ada di sumber lain daripada yang dikutip → peringatan, dan sumber aslinya ikut
  ditampilkan sebagai "terkait — tidak dikutip AI".
- Klaim "sudah terverifikasi" tanpa sumber terverifikasi yang dikutip → peringatan.
- Asumsi/pertanyaan berhuruf non-Latin, atau "pertanyaan klarifikasi" yang hanya mengulang
  pertanyaan pengguna, dibuang.

Pesan menyimpan sumber yang dikutip **beserta data persis yang diberikan ke model**, sehingga
pengguna dapat memeriksa dasar jawaban. Jawaban hanya saran: chat tidak punya tool yang menulis,
menyetujui, atau menerbitkan. Audit mencatat pembuatan run tanpa isi pertanyaan. Pembuat dapat
menghapus percakapannya; data bisnis tidak terpengaruh.

Batasan (uji nyata, LOCAL_DEVELOPMENT §7.7): model 3B sering salah menempatkan kutipan dan pernah
mengklaim status yang tidak ada. Pemeriksaan di atas **menandai**, tidak mengoreksi isi jawaban.
Model yang lebih besar meningkatkan kualitas tanpa perubahan kode.

## ADR-045 — Data demo dibangun lewat API publik, in-process
**Status:** Diterima (Fase 10)

`seed-demo` membuat organisasi, pengguna per peran, klien, dan proyek (seperti sebelumnya), lalu
`app/demo_story.py` memainkan **alur bisnis lengkap** sebagai pengguna demo — estimator, approver,
finance, PM — lewat endpoint yang sama dengan browser (FastAPI `TestClient` in-process, login +
CSRF):

- katalog harga bersumber (terverifikasi, belum terverifikasi, dan harga baru yang belum
  diverifikasi di atas harga lama yang terverifikasi);
- RAB dari harga katalog + satu estimasi manual → disetujui → dokumen terbit; versi 2 draft;
- penawaran 30/40/30 → terbit → diterima klien → SPK → BAST sebagian;
- invoice uang muka → terbit → dibayar sebagian (catatan transfer);
- satu RAB menunggu approval dan satu draft dengan item tanpa harga.

Alasannya: data demo otomatis mematuhi semua aturan (izin, validasi, penomoran, total, snapshot,
idempotensi, audit) dan tidak bisa menyimpang dari logika bisnis seiring perubahan kode. Alur yang
sama dijalankan di tes (`test_demo_story.py`) dan pada database kosong dengan commit sungguhan.
Semua nama berlabel "(Demo)", email `@example.com`; NPWP, rekening bank, dan tanda tangan tidak
dikarang. Ditolak di production.

## ADR-046 — Rate limit endpoint berat dan header keamanan tambahan
**Status:** Diterima (Fase 10)

**Rate limit.** Endpoint yang merender berkas, menerbitkan dokumen, menerima unggahan/impor, atau
memanggil model lokal memakai dependency `limit_expensive`: jendela geser 60 detik per pengguna
(per organisasi), `RATE_LIMIT_EXPENSIVE_PER_MINUTE` (default 30, `0` = mati) → 429 `rate_limited`
dengan `Retry-After`. Disimpan di memori proses — cukup untuk MVP satu proses; dengan beberapa
worker, batas efektif berlipat (DEPLOYMENT §6). Throttle login tetap persisten di database
(terpisah).

**Header.**

- API: tambahan `Cross-Origin-Resource-Policy: same-origin`, `Permissions-Policy`, CSP
  `default-src 'none'; frame-ancestors 'none'` khusus respons JSON (tidak pada PDF/XLSX agar
  penampil PDF browser tidak terganggu), dan HSTS bila `APP_ENV=production`.
- Web: CSP halaman `frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'`
  (dikecualikan dari `/api/*`). `script-src` sengaja tidak dibatasi: Next.js memakai skrip inline
  untuk hidrasi dan nonce akan memaksa semua halaman dinamis.

**Guard production** bertambah: CORS wajib `https://` dan `SESSION_COOKIE_SECURE=false` ditolak.

## ADR-047 — Input angka gaya Indonesia dinormalisasi bila tidak ambigu
**Status:** Diterima (Fase 10)

Uji E2E menunjukkan "18,5" (desimal koma, lazim di Indonesia) ditolak dengan pesan "pakai titik".
Form kini menerima notasi Indonesia yang **tidak mungkin salah baca** dan mengubahnya ke bentuk yang
dipakai API sebelum dikirim (`normalizeDecimal`):

- `18,5` → `18.5`; `1.250.000` → `1250000`; `1.250.000,50` → `1250000.50`; `1.250,5` → `1250.5`.
- `95.000` tetap **ditolak sebagai ambigu** (95 atau 95 ribu?) — aturan Fase 3 tetap berlaku.
- Notasi Inggris berpemisah (`1,250.50`) tidak ditebak dan ditolak.

Berlaku untuk volume, harga satuan, harga katalog, baris invoice, volume BAST, anggaran proyek,
diskon, jumlah pembayaran, dan nilai termin. Server tetap hanya menerima bentuk baku dan memvalidasi
ulang; tidak ada angka yang dikonversi lewat `Number` sebelum dikirim.
