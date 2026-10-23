# API

Base path `/api/v1`. Dokumentasi interaktif (OpenAPI) di `http://127.0.0.1:8000/api/v1/docs`
(nonaktif di production).

## Konvensi

- **Autentikasi:** cookie `rabmate_session` (HttpOnly, SameSite=Lax, Secure di production).
- **CSRF:** semua `POST/PUT/PATCH/DELETE` terautentikasi wajib header `X-CSRF-Token` berisi nilai cookie
  `rabmate_csrf`. Token terikat ke sesi di server. Request dengan header `Origin` di luar
  `CORS_ALLOWED_ORIGINS` ditolak (`403 origin_rejected`).
- **Error:** selalu `{"error": {"code", "message", "details", "request_id"}}`; tidak ada stack trace.
  Kode umum: `unauthenticated` 401, `invalid_credentials` 401, `forbidden` 403, `csrf_failed` 403,
  `not_found` 404, `conflict` 409, `version_conflict` 409, `validation_error` 422, `rate_limited` 429.
- **Objek organisasi lain** selalu `404` (tidak dibedakan dari "tidak ada").
- **Paginasi:** `?page=1&page_size=20` (maks. 100) → `{items, total, page, page_size}`.
- **Sort:** `?sort=name` / `?sort=-created_at`, hanya kunci yang di-whitelist.
- **Desimal:** uang/persentase dikirim dan diterima sebagai **string** (`"1250000.50"`). Angka
  JSON pecahan ditolak karena sudah kehilangan presisi saat di-parse sebagai float.
- **Optimistic locking:** `PATCH` klien/proyek wajib menyertakan `version` terakhir yang dibaca.

## Endpoint (Fase 2)

| Metode & path | Izin | Keterangan |
|---|---|---|
| `GET /health`, `GET /health/live` | publik | Status API/DB |
| `POST /auth/login` | publik | Throttle: 5 gagal/email, 20 gagal/IP per 15 menit → 429 |
| `POST /auth/logout` | sesi | Mencabut sesi |
| `GET /auth/me` | sesi | User, organisasi aktif, role, permission, daftar organisasi |
| `POST /auth/change-password` | sesi | Mencabut sesi lain |
| `POST /auth/switch-organization` | sesi | Pindah organisasi aktif (harus anggota) |
| `GET /organizations/current` | `org.read` | Profil perusahaan |
| `PATCH /organizations/current` | `org.update` | |
| `GET /roles` | sesi | Matriks role → permission |
| `GET /users` | `users.read` | Anggota organisasi |
| `POST /users` | `users.manage` | Buat user baru atau tambahkan user terdaftar |
| `PATCH /users/{user_id}` | `users.manage` | Role/status; minimal satu Owner aktif; sesi user dicabut |
| `GET /clients` | `clients.read` | `q`, `is_active`, `sort`, paginasi |
| `POST /clients` | `clients.write` | |
| `GET /clients/{id}` | `clients.read` | |
| `PATCH /clients/{id}` | `clients.write` | `version` wajib |
| `DELETE /clients/{id}` | `clients.delete` | 409 bila dipakai proyek |
| `GET /projects` | `projects.read` | `q`, `status`, `project_type`, `client_id`, `sort`, paginasi |
| `POST /projects` | `projects.write` | Nomor otomatis `PRJ-<tahun>-<urut>` bila kosong |
| `GET /projects/{id}` | `projects.read` | Termasuk `allowed_status_transitions` |
| `PATCH /projects/{id}` | `projects.write` | `version` wajib; transisi status divalidasi |
| `PUT /projects/{id}/members` | `projects.write` | Ganti daftar anggota (harus anggota aktif organisasi) |
| `DELETE /projects/{id}` | `projects.delete` | |
| `GET /audit-logs` | `audit.read` | Filter `entity_type`, `entity_id`, `actor_id`, `action` |
| `GET /dashboard/summary` | `projects.read` | Hitungan dari DB; `recent_activity` `null` tanpa `audit.read` |

## Endpoint RAB (Fase 3)

| Metode & path | Izin | Keterangan |
|---|---|---|
| `GET /projects/{id}/rab` | `rab.read` | RAB milik proyek |
| `POST /projects/{id}/rab` | `rab.write` | Buat RAB + versi 1 (draft); pajak awal dari proyek; 409 bila proyek selesai/dibatalkan |
| `GET /rab` | `rab.read` | `q`, `status` (versi terbaru), `project_id`, `sort`, paginasi |
| `GET /rab/{id}` | `rab.read` | Metadata + ringkasan semua versi |
| `PATCH /rab/{id}` | `rab.write` | Ubah judul |
| `DELETE /rab/{id}` | `rab.write` | 409 bila pernah disetujui atau sedang direview |
| `POST /rab/{id}/duplicate` | `rab.write` | `{project_id?, title?, version_no?}` → RAB baru (v1 draft) |
| `GET /rab/{id}/compare?from=&to=` | `rab.read` | Perbandingan item dan total dua versi |
| `POST /rab/{id}/versions` | `rab.write` | `{from_version_no?}` → versi baru (draft); 409 bila masih ada versi terbuka |
| `GET /rab/{id}/versions/{n}` | `rab.read` | Item, total, `issues`, `approvals`, `editable`, `allowed_actions`, `can_create_version` |
| `PATCH /rab/{id}/versions/{n}` | `rab.write` | Pajak, diskon, catatan, asumsi; `lock_version` wajib; hanya draft |
| `POST /rab/{id}/versions/{n}/items` | `rab.write` | Tambah item; hanya draft |
| `PUT /rab/{id}/versions/{n}/items/{item}` | `rab.write` | Ganti isi item; `row_version` wajib |
| `DELETE /rab/{id}/versions/{n}/items/{item}?row_version=` | `rab.write` | Hapus item |
| `POST /rab/{id}/versions/{n}/transitions/{action}` | lihat bawah | `{note?}`; `submit` ditolak 422 berisi `details.issues` bila ada kesalahan validasi |
| `GET /approvals/pending` | `rab.approve` | Versi berstatus `in_review` |

Semua mutasi versi/item mengembalikan versi lengkap (termasuk total terbaru dari server).

| Aksi | Dari | Ke | Izin |
|---|---|---|---|
| `submit` | draft | in_review | `rab.write` |
| `withdraw` | in_review | draft | `rab.write` |
| `approve` | in_review | approved (versi disetujui sebelumnya → archived) | `rab.approve` |
| `reject` | in_review | rejected (catatan wajib) | `rab.approve` |
| `reopen` | rejected | draft | `rab.write` |
| `archive` | draft, rejected | archived | `rab.write` |

Rumus (ADR-022): `subtotal item = round2(qty × harga)`, `subtotal = Σ`, `diskon` (persen atau
nominal ≤ subtotal), `DPP = subtotal − diskon`, `pajak = round2(DPP × tarif)` bila dikonfigurasi,
`grand total = DPP + pajak`; round2 = ROUND_HALF_UP.

## Endpoint katalog harga (Fase 4)

| Metode & path | Izin | Keterangan |
|---|---|---|
| `GET /suppliers` | `pricing.read` | `q`, `is_active`, `sort` (`name`, `updated_at`), paginasi |
| `POST /suppliers` | `pricing.write` | |
| `PATCH /suppliers/{id}` | `pricing.write` | `version` wajib; `is_active` |
| `GET /price-catalog` | `pricing.read` | `q`, `category`, `item_type`, `is_active`, `sort`, paginasi; tiap item membawa `prices` (`latest_verified`, `latest_any`, `observation_count`) |
| `POST /price-catalog` | `pricing.write` | Item + `initial_price` opsional (menjadi observasi pertama, `unverified`); 409 bila kode dipakai |
| `GET /price-catalog/categories` | `pricing.read` | Kategori yang dipakai |
| `GET /price-catalog/{id}` | `pricing.read` | Item + seluruh riwayat harga |
| `PATCH /price-catalog/{id}` | `pricing.write` | `version` wajib; ganti satuan → 409 bila sudah ada riwayat harga |
| `POST /price-catalog/{id}/observations` | `pricing.write` | Catat harga baru (`manual`/`vendor_quote`/`external`; `import` hanya lewat impor); satuan = satuan item |
| `POST /price-observations/{id}/verification` | `pricing.verify` | `{status: verified\|rejected, note}`; tanpa sumber → 422; tolak wajib `note` |
| `GET /price-catalog/candidates` | `pricing.read` | `name` (wajib), `unit`, `specification`, `brand`, `location`, `currency`, `limit` ≤ 30 → kandidat katalog + riwayat RAB disetujui dengan `score`, `level`, `unit_compatible`, `reasons`, `warnings` (ADR-026) |
| `GET /price-catalog/imports/template?format=xlsx\|csv` | `pricing.read` | Template berkolom resmi (+ lembar petunjuk di xlsx) |
| `POST /price-catalog/imports` | `pricing.write` | Multipart `file` (.xlsx/.csv, ≤ 5 MB, ≤ 5.000 baris) → pratinjau per baris; 413 bila terlalu besar; 422 bila berkas tidak dapat dibaca |
| `GET /price-catalog/imports/{id}` | `pricing.read` | |
| `POST /price-catalog/imports/{id}/commit` | `pricing.write` | Simpan baris valid (idempoten) → `result` |
| `POST /price-catalog/imports/{id}/discard` | `pricing.write` | |
| `GET /price-sources/external` | `pricing.read` | `{configured, provider, message}` |
| `POST /price-sources/external/search` | `pricing.write` | 503 `external_search_not_configured` selama `PRICE_SEARCH_PROVIDER=none` (ADR-028) |

Item RAB (`POST`/`PUT …/items`) menerima `price_observation_id`; bila diisi, server mengambil harga dan
sumber dari katalog (ADR-029). Respons item membawa `price_observation_id` dan
`price_verification_status`.

## Endpoint dokumen, ekspor & impor item RAB (Fase 5)

| Metode & path | Izin | Keterangan |
|---|---|---|
| `GET /rab/{id}/versions/{n}/preview.pdf` | `rab.read` | Pratinjau PDF data terkini (watermark PRATINJAU, tanpa nomor, tidak disimpan); `?download=true` → attachment |
| `GET /rab/{id}/versions/{n}/export.xlsx` | `rab.read` | Ekspor XLSX data terkini (nilai saja, tanpa rumus) |
| `POST /rab/{id}/versions/{n}/documents` | `documents.issue` | Terbitkan (versi `approved` saja). Header `Idempotency-Key` (8–100 karakter `[A-Za-z0-9_-:.]`): 201 baru, 200 + `Idempotent-Replayed: true` untuk retry; 409 `already_issued` (+`document_id`), 422 `idempotency_key_reused` |
| `GET /documents` | `documents.read` | `q`, `doc_type`, `status`, `rab_id`, `rab_version_id`, `project_id`, `sort` (`issued_at`, `number`), paginasi |
| `GET /documents/{id}` | `documents.read` | Metadata + snapshot + daftar berkas (ukuran, SHA-256) |
| `GET /documents/{id}/files/{pdf\|xlsx}` | `documents.read` | Byte tersimpan saat terbit; `ETag` = SHA-256; PDF inline kecuali `?download=true` |
| `POST /documents/{id}/void` | `documents.issue` | `{reason}` wajib; 409 bila sudah dibatalkan |
| `GET /document-settings` | `documents.read` | Template dokumen (`version` 0 = default) |
| `PUT /document-settings` | `org.update` | Ganti seluruh template; `version` wajib |
| `GET /rab/item-imports/template?format=xlsx\|csv` | `rab.read` | Template impor item RAB |
| `POST /rab/{id}/versions/{n}/imports` | `rab.write` | Multipart `file` → pratinjau per baris (versi draft saja) |
| `GET /rab/{id}/versions/{n}/imports/{job}` | `rab.read` | |
| `POST /rab/{id}/versions/{n}/imports/{job}/commit` | `rab.write` | Tambahkan baris valid sebagai item (idempoten) |
| `POST /rab/{id}/versions/{n}/imports/{job}/discard` | `rab.write` | |

Semua berkas dikirim dengan `Cache-Control: no-store`. `GET /dashboard/summary` kini memuat
`documents` (`issued`, `void`, `approved_rab_not_issued`).

## Endpoint penawaran, invoice & pembayaran (Fase 6)

| Metode & path | Izin | Keterangan |
|---|---|---|
| `GET /quotations` | `rab.read` | `q`, `status`, `project_id`, `rab_id`, `client_response`, `sort`, paginasi |
| `POST /quotations` | `rab.write` | `{rab_version_id, subject?}` — hanya versi disetujui; proyek wajib punya klien |
| `GET /quotations/{id}` | `rab.read` | Termasuk termin (+ invoice per termin), riwayat persetujuan, flag aksi |
| `PATCH /quotations/{id}` | `rab.write` | Isi teks + berlaku sampai; `version` wajib; hanya draft |
| `PUT /quotations/{id}/terms` | `rab.write` | `{version, terms:[{name, basis: percent\|amount, value, due_date?, description?}]}` → nilai dihitung server (ADR-035) |
| `POST /quotations/{id}/transitions/{submit\|withdraw\|approve\|reject\|reopen}` | penyusun: `rab.write`; approve/reject: `documents.approve` | `{note}` (wajib untuk reject) |
| `GET /quotations/{id}/preview.pdf` | `rab.read` | Pratinjau |
| `POST /quotations/{id}/issue` | `documents.issue` | Idempotent (`Idempotency-Key`); → `DocumentOut` |
| `POST /quotations/{id}/response` | `rab.write` | `{response: accepted\|declined, note}`; hanya penawaran terbit |
| `POST /quotations/{id}/void` | `documents.issue` | `{reason}`; ditolak bila ada invoice aktif |
| `DELETE /quotations/{id}` | `rab.write` | Hanya draft/ditolak |
| `POST /quotations/{id}/terms/{term}/invoice` | `finance.write` | Invoice termin (penawaran terbit + diterima; 1 per termin) |
| `GET /invoices` | `finance.read` | `q`, `status`, `payment_state` (unpaid/partial/paid), `overdue`, `project_id`, `client_id`, `quotation_id`, `sort` |
| `POST /invoices` | `finance.write` | Invoice manual `{project_id, title, due_date?, notes?}` |
| `GET /invoices/{id}` | `finance.read` | Baris, alokasi pembayaran, `outstanding`, `payment_state`, `overdue`, flag aksi |
| `PATCH /invoices/{id}` | `finance.write` | Draft; `version`; baris & pajak hanya untuk invoice manual (total dihitung server) |
| `POST /invoices/{id}/transitions/{action}` | seperti penawaran (penyusun `finance.write`) | Submit butuh baris, total > 0, jatuh tempo ≥ hari ini |
| `GET /invoices/{id}/preview.pdf` | `finance.read` | |
| `POST /invoices/{id}/issue` | `documents.issue` | Nomor `INV-YYYY-NNNN` + tanggal terbit hari ini; idempoten |
| `POST /invoices/{id}/void` | `documents.issue` | Ditolak bila sudah ada pembayaran |
| `DELETE /invoices/{id}` | `finance.write` | Hanya draft/ditolak |
| `GET /payments` | `finance.read` | `client_id`, `invoice_id`, `status`, `sort` |
| `POST /payments` | `finance.write` | `{client_id, payment_date, amount, currency, method, reference?, notes?, allocations:[{invoice_id, amount}]}`; `Idempotency-Key` |
| `GET /payments/{id}` | `finance.read` | |
| `POST /payments/{id}/allocations` | `finance.write` | Alokasikan sisa pembayaran |
| `POST /payments/{id}/void` | `finance.write` | `{reason}`; melepas alokasi |

`GET /dashboard/summary` kini memuat `quotations` (draft, review, menunggu tanggapan, diterima) dan
`billing` (sisa tagihan, lewat jatuh tempo, diterima bulan ini — per mata uang — dan termin jatuh
tempo ≤ 30 hari yang belum ditagih). `GET /documents` menerima filter `quotation_id`/`invoice_id`.

## Endpoint SPK & BAST (Fase 7)

| Metode & path | Izin | Keterangan |
|---|---|---|
| `GET /spk` | `projects.read` | `q`, `status`, `project_id`, `quotation_id`, `sort`, paginasi; `bast_count` per SPK |
| `POST /spk` | `projects.write` | `{quotation_id, title?}` — hanya penawaran terbit + diterima klien; 1 SPK aktif per penawaran (409) |
| `GET /spk/{id}` | `projects.read` | Nilai kontrak & termin (dari penawaran, + invoice per termin), riwayat persetujuan, flag aksi |
| `PATCH /spk/{id}` | `projects.write` | Draft; `version`; judul, periode, lokasi, lingkup, ketentuan, catatan, nama/jabatan penanda tangan |
| `POST /spk/{id}/transitions/{action}` | penyusun `projects.write`; approve/reject `documents.approve` | Submit wajib tanggal mulai, lingkup, nama penanda tangan kedua pihak (detail per field) |
| `GET /spk/{id}/progress` | `projects.read` | Item kontrak: volume kontrak, diserahkan (BAST terbit), dalam proses, sisa; `final_bast` |
| `GET /spk/{id}/preview.pdf` | `projects.read` | Pratinjau |
| `POST /spk/{id}/issue` | `documents.issue` | Nomor `SPK-YYYY-NNNN` + tanggal SPK; idempoten (`Idempotency-Key`); → `DocumentOut` |
| `POST /spk/{id}/void` | `documents.issue` | `{reason}`; ditolak bila masih ada BAST yang belum dibatalkan |
| `DELETE /spk/{id}` | `projects.write` | Hanya draft/ditolak |
| `GET /bast` | `projects.read` | `q`, `status`, `kind`, `spk_id`, `project_id`, `sort` |
| `POST /bast` | `projects.write` | `{spk_id, kind: partial\|final, title?, prefill_remaining?}` — hanya SPK terbit; 1 BAST akhir aktif per SPK |
| `GET /bast/{id}` | `projects.read` | Baris, riwayat persetujuan, flag aksi |
| `PATCH /bast/{id}` | `projects.write` | Draft; `version`; header + `items:[{rab_item_id?, description, quantity, unit, condition?}]` — volume dicek terhadap sisa kontrak (422 per baris) |
| `POST /bast/{id}/transitions/{action}` | seperti SPK | Submit wajib tanggal serah terima ≤ hari ini, nama kedua pihak, ≥ 1 baris; volume dicek ulang |
| `GET /bast/{id}/preview.pdf` | `projects.read` | Pratinjau |
| `POST /bast/{id}/issue` | `documents.issue` | Volume dicek ulang di bawah kunci SPK; nomor `BAST-YYYY-NNNN`; idempoten |
| `POST /bast/{id}/void` | `documents.issue` | `{reason}`; volumenya tidak lagi dihitung diserahkan |
| `DELETE /bast/{id}` | `projects.write` | Hanya draft/ditolak |

`GET /quotations/{id}` kini memuat `spk` (id, nomor, status) dan `can_create_spk`; penawaran dengan
SPK aktif tidak dapat dibatalkan atau diubah tanggapan kliennya. `GET /documents` menerima filter
`spk_id`/`bast_id`; dokumen SPK/BAST dibatalkan dari endpoint sumbernya. `GET /dashboard/summary`
memuat `workorders` (penawaran diterima tanpa SPK, SPK menunggu review, SPK berjalan tanpa BAST akhir
terbit, BAST menunggu review). `PUT /document-settings` menerima `spk_terms` dan `bast_terms`.

## Endpoint asisten AI lokal (Fase 8)

| Metode & path | Izin | Keterangan |
|---|---|---|
| `GET /ai/status` | login (`org.read`) | `{enabled, state: disabled\|ready\|unavailable\|unsafe, message, model, toolsets}`; `?fresh=true` melewati cache 30 detik |
| `POST /rab/{id}/versions/{n}/ai-runs` | `ai.use` + `rab.write` | `{kind: rab_draft, description}` atau `{kind: extract_items, text, source_label?, number_format: id\|en}`; versi draft; 503 `ai_disabled`/`ai_unavailable`/`ai_unsafe_config`; 409 `ai_busy`; → 202 run (diproses di latar belakang) |
| `GET /rab/{id}/versions/{n}/ai-runs` | `rab.read` | 20 run terakhir versi tsb. |
| `GET /ai-runs/{id}` | `rab.read` | Status, input, `context`, hasil (item + peringatan + asumsi/pertanyaan), error, model, `can_apply` |
| `POST /ai-runs/{id}/apply` | `ai.use` + `rab.write` | `{items:[{index, name, quantity, unit, item_type?, price: none\|catalog\|document, price_observation_id?}]}` → item ditambahkan ke versi draft; idempoten |
| `POST /ai-runs/{id}/discard` | `ai.use` | Hanya run berhasil/gagal yang belum diterapkan |

`GET /health` kini memeriksa AI saat `AI_ENABLED=true` (`ai: ok|error`); status AI tidak membuat
API "degraded".

## Endpoint dokumen sumber & chat proyek (Fase 9)

| Metode & path | Izin | Keterangan |
|---|---|---|
| `POST /projects/{id}/source-documents` | `ai.use` + `rab.write` | Multipart `file` (PDF, XLSX, CSV/TXT, PNG/JPEG; maks. `UPLOAD_MAX_MB`). Jenis dari isi file, ekstensi harus cocok. → 201 `{…, duplicate}`; file yang sama di proyek yang sama mengembalikan salinan lama (`duplicate: true`). 413 `payload_too_large`, 422 format |
| `GET /projects/{id}/source-documents` | `rab.read` | 50 dokumen terbaru proyek |
| `GET /source-documents/{id}` | `rab.read` | Metadata (nama, jenis, ukuran, SHA-256, pengunggah) |
| `GET /source-documents/{id}/text` | `rab.read` | `{read, pages:[{no, label, method: teks\|tabel\|ocr\|kosong, lines}], warnings}` — teks yang terbaca (setelah diproses asisten) |
| `GET /source-documents/{id}/file` | `rab.read` | File asli, selalu `attachment` + `nosniff` + `no-store` |
| `POST /rab/{id}/versions/{n}/ai-runs` | `ai.use` + `rab.write` | Tambahan: `{kind: extract_document, source_document_id, number_format}` — dokumen harus milik proyek RAB itu (422 bila lain, 404 bila tidak ada/organisasi lain); format angka XLSX selalu `id` |
| `GET /projects/{id}/ai-conversations` | `ai.use` + `projects.read` | Percakapan **milik sendiri** di proyek itu (30 terbaru, dengan jumlah pesan) |
| `POST /projects/{id}/ai-conversations` | `ai.use` + `projects.read` | `{message}` (2–2.000 karakter) → 202 percakapan baru; jawaban disusun di latar belakang |
| `GET /ai-conversations/{id}` | pembuat saja | Pesan (jawaban dengan `sources[{id, kind, label, ref, data, cited}]`, `warnings`, `assumptions`, `questions`), `latest_run` (status/error), `unavailable` |
| `POST /ai-conversations/{id}/messages` | pembuat saja | `{message}` → 202; 409 bila jawaban sebelumnya masih diproses atau org sedang memakai AI |
| `DELETE /ai-conversations/{id}` | pembuat saja | 204; 409 bila jawaban masih diproses |

`GET /ai/status` kini juga mengembalikan `ocr: {available, message}`, `upload_max_mb`, dan
`accepted_files`. `GET /ai-runs/{id}` tidak mengembalikan jawaban chat (run `chat_answer` hanya
lewat percakapannya); hasil `extract_document` memuat `document: {pages, lines, chunks, ocr_pages,
lines_left_out}` dan setiap item memuat `source_page` + `source_page_line`.

## Batas permintaan berat (Fase 10)

Endpoint yang merender berkas, menerbitkan dokumen, menerima unggahan/impor, atau memanggil model
lokal dibatasi `RATE_LIMIT_EXPENSIVE_PER_MINUTE` (default 30) permintaan per pengguna per menit:
pratinjau PDF/ekspor XLSX RAB, pratinjau & penerbitan penawaran/invoice/SPK/BAST, penerbitan
dokumen RAB, unggah dokumen sumber, impor katalog & item RAB (unggah dan commit), permintaan AI dan
pesan chat. Melewati batas → `429 rate_limited` dengan header `Retry-After` (detik). Unduhan berkas
yang sudah tersimpan tidak dibatasi.

## Siklus status proyek

```
prospect → active | cancelled
active   → on_hold | completed | cancelled
on_hold  → active | cancelled
completed → active        (dibuka kembali)
cancelled → prospect      (dihidupkan kembali)
```
