# DESIGN.md: arah visual RABmate AI

Arah ini dipilih pemilik produk pada 2026-10-23 ("Tinta & Stabilo"). Draf awalnya disusun agen
dari fakta produk, lalu disetujui pemilik. Semua pekerjaan UI membaca berkas ini dulu, lalu
menerapkan filter antislop di atasnya.

## Identitas

RABmate AI adalah alat kerja untuk menyusun RAB, mengelola harga bersumber, dan menerbitkan
dokumen proyek (penawaran, invoice, SPK, BAST) bagi tim estimasi, proyek, dan keuangan di
Indonesia. Layarnya padat angka uang, dan dokumen yang dihasilkannya dicetak atau dikirim ke
klien.

## Kepribadian

Presisi, tenang, dan bisa dipercaya, dengan kehangatan meja kerja: kertas, tinta, dan stabilo.
Bukan "aplikasi teknologi", bukan dasbor futuristis.

## Bacaan desain dan dial

Aplikasi kerja estimasi biaya dan dokumen untuk estimator, PM, approver, dan finance, bergaya
kertas kerja yang tenang dan presisi.

**Dial: ENERGY 1 / RHYTHM 2 / MOTION 1**

- ENERGY 1: layar kerja yang padat data; tampilan tidak boleh berteriak.
- RHYTHM 2: konsisten, dengan variasi yang disengaja (satu titik fokus per layar, kartu
  sekunder lebih kecil).
- MOTION 1: hanya transisi hover dan fokus, ditambah indikator memuat yang memang menandai proses.

## Motif identitas

1. **Tinta yang sama di layar dan di kertas.** Biru tinta `#1F4E79` adalah warna aksen bawaan
   semua PDF terbit, dan menjadi warna utama UI.
2. **Stabilo pada angka yang menentukan.** Seperti estimator menyorot angka di RAB cetak, satu
   angka terpenting di tiap layar diberi latar kuning stabilo: grand total RAB, total penawaran,
   sisa tagihan invoice (total tagihan selama belum terbit), total dokumen terbit, dan sisa tagihan
   di dashboard. Ini satu-satunya aksen. Komponennya `KeyFigure` (`components/ui/KeyFigure.tsx`).

## Palet

Inti: tinta (utama) dan netral kertas. Aksen: stabilo. Status (sukses, peringatan, bahaya) hanya
untuk status. Semua pasangan teks lolos WCAG AA (diperiksa dengan `contrast-check.py` antislop).

| Peran | Terang | Gelap | Dipakai untuk |
|---|---|---|---|
| Latar (kertas) | `#F7F5F0` | `#0F1720` | Kanvas halaman |
| Permukaan | `#FFFFFF` | `#17212D` | Kartu, tabel, dialog |
| Permukaan redup | `#EFEBE3` | `#1C2937` | Kepala tabel, hover, isian netral |
| Garis rambut | `#E2DDD3` | `#2A3846` | Pemisah kartu dan baris (dekoratif) |
| Garis kontrol | `#7D8594` | `#6E7D90` | Batas input, checkbox, select (≥ 3:1) |
| Teks | `#14202E` | `#E8EDF2` | Teks utama |
| Teks redup | `#566070` | `#9AA7B5` | Label, keterangan |
| Tinta (utama) | `#1F4E79` | `#8DB8E3` | Tombol utama, tautan, navigasi aktif, cincin fokus |
| Tinta hover | `#173D60` | `#A6C8EA` | Hover tombol utama |
| Teks di atas tinta | `#FFFFFF` | `#0F1720` | Label tombol utama |
| Tinta lembut | `#E4ECF4` | `#1C2B3B` | Inisial avatar, ikon keadaan kosong |
| Stabilo (aksen) | `#F5C02E` | `#F5C02E` | Latar satu angka terpenting per layar |
| Teks di atas stabilo | `#14202E` | `#0F1720` | Angka yang disorot |
| Sukses | `#166534` / latar `#E7F3EA` | `#6EDC98` / `#13261C` | Status disetujui, terbit, lunas |
| Peringatan | `#9A3412` / latar `#FBEDE3` | `#FDBA74` / `#2B1D12` | Status perlu perhatian (sengaja jingga, beda dari stabilo) |
| Bahaya | `#B42318` / latar `#FBEAE8` | `#FCA5A5` / `#2E1616` | Galat, tolak, batal; tombol hapus |

Aturan pakai:

- Stabilo: paling banyak satu per layar, hanya untuk angka atau fakta penentu. Tidak untuk
  tombol, ikon, garis, latar kartu, atau hiasan. Dua pengecualian yang disengaja: di halaman
  masuk stabilo menandai frasa inti produk ("satu tempat"), dan teks yang diseleksi pengguna
  memakai stabilo transparan seperti coretan stabilo sungguhan.
- Sidebar adalah "sampul" tinta buku kerja: latar `#15283B` (gelap `#0B121A`), teks `#F1F4F7`,
  teks redup `#B9C6D4`. Halaman aktif tampil sebagai tab kertas (`#F7F5F0`, teks tinta); di tema
  gelap tab aktif memakai tinta terang `#8DB8E3` dengan teks `#0F1720`.
- Tinta: paling banyak satu tombol utama per tampilan; tombol lain sekunder atau ghost.
- Tanpa gradien, glow, latar grid, atau glassmorphism.

## Tipografi

**Plus Jakarta Sans** (Tokotype, lisensi OFL), dirancang untuk identitas kota Jakarta: huruf
lokal yang lebar, terbuka, dan jelas untuk layar padat. Bobot 400 (teks), 500 (label), 600
(judul bagian), 700 (judul halaman dan angka penentu). Angka uang selalu tabular agar kolom rata.
Ukuran judul mengecil di ponsel.

## Bentuk dan kedalaman

- Radius: 6px untuk kontrol (tombol, input), 10px untuk kartu dan dialog. Bentuk pil hanya untuk
  badge status.
- Bayangan: hanya untuk lapisan yang melayang (menu, dialog, toast). Kartu tetap datar dengan
  garis rambut.
- Header menempel solid, tanpa blur.

## Tema

Terang dan gelap sama-sama didukung, dengan pilihan Ikuti sistem / Terang / Gelap. Tidak ada
alasan produk untuk memaksakan satu tema.

## Ikon

Tetap Lucide (sudah dipakai di seluruh kode). Setiap ikon harus relevan dengan isinya; bila tidak
ada yang relevan, tanpa ikon.
