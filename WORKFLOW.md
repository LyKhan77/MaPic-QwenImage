# MaPic Workflow

Panduan alur kerja MaPic: bagaimana satu generasi mengalir dari klik pengguna sampai gambar tersimpan, bagaimana siklus hidup model, bagaimana cara mengembangkan dan men-deploy, serta runbook untuk masalah yang paling sering muncul.

Untuk desain sistem dan alasannya, lihat `ARCHITECTURE.md`. Untuk operasional container, lihat `deploy/docker/README.md`.

Terakhir ditinjau: **2026-09-23**

---

## 1. Alur satu generasi

### Status yang dilihat pengguna

```
queued ──► running ──► saving ──► selesai (gambar muncul di kanvas)
   │           │          │
   │           │          └─ unggah ke Supabase + tulis baris riwayat
   │           └─ ComfyUI menjalankan step 1..40
   └─ menunggu lock backend (hanya satu generasi pada satu waktu)
```

Antrean dan status aktif terlihat di pil kanan bawah (`1/10 active`). Job milik sendiri bisa diklik untuk kembali ke tampilan progresnya; job milik pengguna lain hanya bisa dilihat.

### Tahapan yang dilaporkan engine

Selama `running`, badge kanan atas mengikuti progres per node dari ComfyUI:

```
warmup → encoding → diffusion → decoding
```

`diffusion` adalah bagian terpanjang dan satu-satunya yang melaporkan hitungan step. Qwen-Image 2.1 tidak punya tahap autoregresif, jadi tidak ada lagi `ar_sampling` seperti pada model sebelumnya.

### Perkiraan waktu (1K, 40 step, terukur di host ini)

| Skenario | Waktu |
|---|---|
| T2I — job pertama setelah model keluar dari VRAM | ~50 detik |
| T2I — model sudah hangat | **32–34 detik** |
| T2I dengan CFG aktif (`true_cfg_scale` 2.0 + negative prompt) | ~63 detik |
| I2I — 1 gambar referensi | ~50 detik |
| I2I — 3 gambar referensi | ~84 detik |

Angka-angka ini dipakai `frontend/src/lib/generation.ts` (`estimateTotalSeconds()`) untuk menghitung perkiraan waktu di UI. Kalau host berubah, kalibrasi ulang di situ.

---

## 2. Image-to-image dan iterasi berantai

### Cara mengirim referensi

Lampirkan sampai 10 gambar di bar input. Facade akan mengunggahnya ke ComfyUI dan memakai node `LoadImage` + `TextEncodeQwenImageEdit`.

### Pola yang paling sering dipakai: menyempurnakan hasil

Ini sudah otomatis — tidak ada tombol khusus:

1. Setelah generasi selesai, **bar input di bawah otomatis membawa prompt dan gambar hasil** sebagai referensi.
2. Ubah prompt sesuka hati, lalu kirim. Model akan memakai gambar sebelumnya sebagai acuan, bukan mulai dari nol.
3. Mengklik item di riwayat juga memuat ulang prompt + gambarnya ke bar input, jadi iterasi bisa dilanjutkan kapan saja.

**Yang perlu diantisipasi:** setiap iterasi menambah satu referensi, dan waktu naik dari ~32 detik (T2I) menjadi ~50 detik (I2I 1 referensi). Teks di dalam gambar juga akan **bergeser** setiap kali digenerasi ulang — kalau tulisan harus presisi, kerjakan di iterasi terakhir atau overlay setelahnya.

---

## 3. Siklus hidup model

```
kosong ──(job pertama)──► dimuat ──(1 jam idle)──► dikosongkan
          ~18 detik              otomatis
```

- **Auto-load:** tidak ada langkah manual. Job pertama memicu pemuatan; pengguna pertama menanggung waktunya (~50 detik, bukan 32).
- **Warmup manual:** tombol load di badge status memicu satu step 256×256 lebih dulu supaya antrean berikutnya cepat.
- **Unload:** otomatis setelah 1 jam tanpa generasi, untuk membebaskan VRAM bagi proses lain di server. Bisa juga manual dari UI.
- **Progres pemuatan:** facade melaporkan segmennya lewat `/v1/system/load/state`, dan frontend memulihkan tampilan itu setelah refresh.

Model dimuat ulang setiap kali container `comfyui` restart — termasuk setelah reboot. Selama container hidup, model tetap tinggal di VRAM walau tidak ada aktivitas sampai batas 1 jam itu.

---

## 4. Kapasitas dan antrean

| Aturan | Nilai | Perilaku saat dilanggar |
|---|---|---|
| Generasi bersamaan | 1 | Job berikutnya `queued` |
| Antrean global | 10 job | HTTP **429** dengan pesan yang jelas |
| Referensi per request | 10 | Validasi request menolak |
| Resolusi | 1024 | HTTP **400** (bukan OOM) |

Validasi request terjadi **sebelum** job masuk antrean. Jadi request yang salah bentuk tidak "memakan" slot antrean dan tidak membuat pengguna lain menunggu lebih lama.

---

## 5. Riwayat dan penghapusan

1. Setelah gambar selesai, backend mengunggah PNG ke bucket `generated_images` dengan path `{user_id}/{uuid}.png`.
2. Baris ditulis ke `public.generations`, dan frontend menampilkan `public_url`.
3. Menghapus item riwayat menghapus **objek storage lebih dulu**, baru baris database — supaya tidak ada baris yang menunjuk ke gambar yang sudah hilang.

Catatan: endpoint hapus saat ini bekerja berdasarkan `id` saja tanpa memverifikasi pemiliknya. Lihat "Notes And Gaps" di `database-schema.md`.

---

## 6. Alur kerja prompt (praktik, bukan teori)

Bagian ini murni hasil pengujian di host ini.

### Teks di dalam gambar — penentu terbesarnya adalah disiplin prompt

Yang benar-benar menaikkan kualitas teks, berurutan dari yang paling berpengaruh:

1. **Tulis teks persisnya di dalam tanda kutip.** `headline reads "COOLER BY DESIGN"` jauh lebih baik daripada `with a short headline`.
2. **Pendek.** 2–4 kata per blok teks. Semakin panjang, semakin cepat rusak.
3. **Sebutkan tipografinya dan posisinya.** Gaya, ketebalan, warna, dan di mana letaknya relatif terhadap objek lain.
4. **Satu blok teks per gambar.** Dua blok teks cenderung saling merusak.

Yang **tidak** membantu: menaikkan jumlah step. 60 step justru memunculkan artefak ghosting tanpa teks yang lebih baik. CFG 2.0–2.5 + negative prompt menggandakan waktu dan hasilnya tidak lebih baik secara konsisten.

### Batas keras

**1 MP.** Teks kecil (label, keterangan bagian, tulisan di poster banyak kolom) akan selalu kabur pada 1024×1024. Kalau hasil harus tajam dan presisi — misalnya poster marketing — kerjakan teksnya sebagai **overlay setelah generasi**, bukan berharap model menggambarnya benar.

### Contoh prompt yang bekerja

```
marketing poster for a data center containment product, the headline reads
"COOLER BY DESIGN" in bold white sans-serif at the top, below it a detailed
exploded view of a containment rack with labeled panels, dark blue background,
technical product illustration, high detail
```

### Untuk iterasi I2I

Ubah **satu hal per iterasi**. Mengubah prompt dan komposisi sekaligus membuat sulit tahu mana yang berpengaruh — dan karena teks bergeser tiap iterasi, perubahan yang menumpuk akan cepat menjauh dari hasil yang tadinya bagus.

---

## 7. Alur kerja pengembangan

### Menjalankan stack

```bash
cd deploy/docker
docker compose up -d            # build bila image belum ada
docker compose ps               # status + healthcheck
docker compose logs -f comfyui  # log satu layanan
```

Skrip `start-app.sh` di root repo hanya membungkus perintah ini.

### Mengubah satu bagian

| Yang diubah | Cara menerapkan | Perlu build? |
|---|---|---|
| Kode facade (`qwen_image_server/`) | `docker compose build qwen-image && docker compose up -d qwen-image` | Ya (kecil, ~30 detik) |
| Kode backend (`backend/`) | `docker compose build backend && docker compose up -d backend` | Ya (kecil) |
| Kode frontend (`frontend/`) | `docker compose build frontend && docker compose up -d frontend` | Ya (~1 menit) |
| Nilai di `backend/.env` | `docker compose restart backend` | **Tidak** |
| Variabel di `deploy/docker/.env` | `docker compose up -d` | Tidak untuk backend/facade; **ya** untuk frontend (nilainya ditanam saat build) |
| Ganti model / kuantisasi | Taruh file, ubah `QWEN_GGUF_NAME`, `up -d qwen-image` | **Tidak** |

Ini keuntungan utama pemisahan per folder: rebuild selalu menyentuh satu layanan saja.

### Deploy ke server

```bash
# di Mac
git push origin main

# di server
cd ~/apps/mapic-qwen && git pull --ff-only
cd deploy/docker && docker compose build <layanan> && docker compose up -d <layanan>
```

### Aturan branch

- `main` mencerminkan apa yang berjalan di server.
- Perubahan bersifat fitur atau eksperimen dikerjakan di branch sendiri, lalu di-merge.
- Jangan commit file `.env` — hanya `.env.example` yang masuk repo.

### Checklist sebelum menyatakan selesai

- [ ] `npx tsc --noEmit` di `frontend/` lolos
- [ ] `docker compose ps` — semua layanan Up, comfyui `healthy`
- [ ] `curl http://127.0.0.1:8281/api/health` mengembalikan `{"status":"ready"}`
- [ ] Satu generasi T2I berhasil end-to-end dan muncul di riwayat
- [ ] Kalau menyentuh I2I: satu generasi dengan referensi berhasil
- [ ] Kalau menyentuh UI: buka dari LAN (`http://192.168.2.142:5151`), bukan hanya localhost

---

## 8. Runbook

### Tugas rutin

```bash
# Lihat riwayat container
docker compose logs --tail=100 backend

# Restart satu layanan tanpa rebuild
docker compose restart qwen-image

# Hentikan semua (model tetap di host)
docker compose down

# Lihat gambar hasil di dalam container
docker compose exec comfyui ls -la /opt/ComfyUI/output

# Uji GPU dari dalam container
docker compose exec comfyui python -c "import torch; print(torch.cuda.get_device_name(0))"
```

### Masalah yang sering muncul

| Gejala | Sebab | Tindakan |
|---|---|---|
| `unet_name ... not in []` | Folder `diffusion_models/` tidak ada di direktori model | Buat folder + symlink, lalu `docker compose restart comfyui` |
| Generasi pertama 50 detik | Model baru dimuat | Normal; job kedua kembali ~32 detik |
| `{"status":"unloaded"}` di health | Model dikosongkan setelah idle | Normal; job berikutnya memuat ulang |
| HTTP 429 | Antrean global penuh (10 job) | Tunggu; indikator kanan bawah menunjukkan posisinya |
| HTTP 400 soal resolusi | Diminta 2K | Host ini 1K; ubah `QWEN_MAX_RESOLUTION` hanya bila VRAM mencukupi |
| Layar putih di browser | Bundle lama di cache | Hard refresh (`Cmd+Shift+R`) |
| Modal settings terpotong | Seharusnya sudah diperbaiki lewat portal ke `document.body` | Kalau muncul lagi, periksa `createPortal` di `PromptInput.tsx` |
| GPU tidak terlihat container | NVIDIA Container Toolkit tidak terpasang | Lihat catatan GPU di `deploy/docker/README.md` |

### Rollback ke systemd

Unit systemd lama masih terpasang tetapi `disabled`:

```bash
docker compose down
sudo systemctl enable --now comfyui qwen-image mapic-backend mapic-frontend
```

Jangan menjalankan keduanya bersamaan — port dan VRAM akan bentrok.
