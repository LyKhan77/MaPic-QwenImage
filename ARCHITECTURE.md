# MaPic Architecture

Dokumen ini menjelaskan bentuk sistem, tanggung jawab tiap komponen, dan alasan di balik keputusan desainnya. Untuk prosedur operasional sehari-hari lihat `deploy/docker/README.md`; untuk alur langkah demi langkah lihat `WORKFLOW.md`.

Terakhir ditinjau: **2026-09-23**

---

## 1. Ringkas

MaPic mengubah prompt teks (dan sampai 10 gambar referensi) menjadi gambar memakai **Qwen-Image 2.1** yang berjalan **lokal**. Tidak ada API pihak ketiga, tidak ada biaya per gambar, tidak ada rate limit, dan tidak ada trafik keluar jaringan.

Seluruh stack berjalan sebagai **empat container Docker** di satu server (`gspe-ai2`), memakai **satu GPU** (RTX 5080 16 GB).

```
┌──────────────────────── jaringan kantor ────────────────────────┐
│                                                                  │
│  Browser ──► frontend :5151 (nginx)                             │
│                 │  SPA hasil build Vite                          │
│                 │  fetch ke /api/*                               │
│                 ▼                                                │
│              backend :8281 (FastAPI)                             │
│                 │  auth session, riwayat, storage                │
│                 │  generation lock, antrean global               │
│                 ▼                                                │
│           network internal Docker (bridge)                       │
│                 │                                                │
│              qwen-image :30000 (facade)   ← tidak diekspos host  │
│                 │  menyusun graph, meneruskan progres            │
│                 ▼                                                │
│              comfyui :8188                ← hanya 127.0.0.1      │
│                 │  menjalankan model di GPU 1                    │
│                 ▼                                                │
│              GPU 1: RTX 5080 16 GB                               │
│                                                                  │
│  Volume read-only: folder model GGUF di host → /models           │
└──────────────────────────────────────────────────────────────────┘
                    │
                    ▼  (keluar jaringan, hanya saat simpan/riwayat)
              Supabase: Postgres + Storage + Auth
```

---

## 2. Tanggung jawab komponen

| Komponen | Bahasa / Basis | Tanggung jawab | Yang **tidak** dilakukannya |
|---|---|---|---|
| **frontend** | React + Vite, disajikan nginx | UI kanvas, riwayat, modal settings, indikator antrean; memegang sesi Supabase Auth | Tidak memanggil ComfyUI atau facade; tidak menyimpan rahasia |
| **backend** | FastAPI | Auth via sesi pengguna, validasi request, antrean + lock generasi, unggah hasil ke Supabase, riwayat, hapus; juga menjalankan **worker cutout CPU** (`rembg` + `isnet-general-use`) di jalur terpisah dari antrean Qwen | Tidak tahu apa itu node ComfyUI; jalur cutout tidak menyentuh GPU maupun facade |
| **qwen-image** (facade) | FastAPI, tanpa torch | Menerjemahkan kontrak API lama menjadi graph ComfyUI; meneruskan progres per node; warmup saat load | Tidak menyentuh Supabase; tidak menyimpan state gambar |
| **comfyui** | ComfyUI + ComfyUI-GGUF | Menjalankan model, mengelola VRAM, menyimpan hasil ke disk container | Tidak tahu apa pun tentang pengguna, riwayat, atau prompt produk |
| **Supabase** | Layanan eksternal | Auth, Postgres (`generations`), Storage (PNG publik) | Tidak terlibat dalam inference |

Pemisahan ini disengaja: **facade adalah satu-satunya tempat yang tahu mesin inference-nya ComfyUI.** Mengganti engine (misalnya pindah ke SGLang-Diffusion atau vLLM-Omni) cukup mengubah facade; backend dan frontend tidak perlu disentuh.

---

## 3. Siklus hidup satu request

### Text-to-image

1. Browser mengirim `POST /api/generate` ke backend (`:8281`) berisi prompt, `user_id`, dan parameter opsional.
2. Backend memvalidasi request **di luar lock** — request tidak valid langsung ditolak tanpa ikut mengantre.
3. Backend mengambil `_generation_lock`. Selama menunggu, job berstatus `queued` dan terlihat di indikator antrean.
4. Backend memanggil facade (`POST /v1/images/generations`).
5. Facade menyusun graph ComfyUI (loader GGUF + CLIP + VAE → text encode → sampler → VAE decode → save) dan mengirimnya ke ComfyUI.
6. ComfyUI memuat komponen secara bergantian (*dynamic VRAM loading*), menjalankan 40 step, dan menyimpan PNG.
7. Facade mengunduh PNG dari ComfyUI dan mengembalikannya ke backend.
8. Backend mengunggah PNG ke Supabase Storage dan menulis baris ke `public.generations`.
9. Backend melepas lock; job berikutnya di antrean jalan.
10. Browser menampilkan gambar dan memperbarui riwayat.

Bottleneck-nya jelas: **langkah 6**. Waktu terukur 1K/40 step ada di `README.md`.

### Image-to-image

Sama, kecuali:

- Browser mengirim gambar referensi sebagai base64.
- Facade mengunggah tiap gambar ke ComfyUI (`/upload/image`) lalu memakai node `LoadImage` + `TextEncodeQwenImageEdit` (sampai 10 referensi).
- Waktu naik: 1 referensi ~50 detik, 3 referensi ~84 detik.

---

## 4. Keputusan desain dan alasannya

### 4.1 ComfyUI + GGUF, bukan diffusers

**Dipilih:** ComfyUI sebagai engine, model kuantisasi GGUF.

**Alasan:** jalur diffusers dicoba lebih dulu dan **gagal di host ini**, dengan tiga kegagalan berurutan:

| Percobaan | Kegagalan |
|---|---|
| `device_map="balanced"` + spill CPU | `Expected all tensors to be on the same device` di text encoder Qwen3-VL |
| Kuantisasi 8-bit | text encoder ditempatkan di device `meta` |
| bf16 penuh (29,4 GiB) | OOM di kartu 16 GB |
| `enable_model_cpu_offload` | Tidak dijalankan — RAM sisa hanya ~29 GB dan dipakai service produksi lain |

ComfyUI berhasil karena **memuat komponen bergantian, bukan bersamaan**: VAE 644 MB → text encoder 8.916 MB → DiT 7.368 MB. Puncak VRAM ~13,7 GB, menyisakan ~2,5 GiB.

Konsekuensi yang diterima: kita bergantung pada API graph ComfyUI, bukan API Python yang stabil. Ini dimitigasi dengan memin commit ComfyUI dan node GGUF di Dockerfile.

### 4.2 Kuantisasi Q8_0

Model resmi 31 GB tidak muat; Q8_0 (7,07 GiB) praktis setara bf16 secara kualitas dan muat. Q4_K_M disimpan sebagai cadangan bila suatu saat butuh ruang lebih — konsekuensinya kualitas turun dan (pada beberapa kasus) waktu naik.

Menggantinya **tidak perlu build ulang image**: cukup taruh file di folder model dan ubah `QWEN_GGUF_NAME` di compose.

### 4.3 Satu GPU, dipin ke device 1

**Dipin**, bukan dibiarkan otomatis. GPU 0 pernah lepas dari bus PCIe (Xid 79, lalu Xid 154) sehingga tidak dipercaya untuk beban produksi. Pinning dilakukan lewat `NVIDIA_VISIBLE_DEVICES` pada container.

**Kenapa bukan multi-GPU?** Ini bukan keterbatasan model, melainkan keterbatasan engine: ComfyUI menempatkan satu model utuh di satu device. Stack yang mendukung sharding (diffusers, SGLang-Diffusion, vLLM-Omni) justru yang gagal di sini karena manajemen memorinya. Menambah GPU ke satu proses ComfyUI tidak akan mempercepat apa pun.

### 4.4 Docker menggantikan systemd

Empat unit systemd digantikan satu compose project `mapic`. Alasan praktisnya:

- Reboot-safe tanpa skrip: `restart: unless-stopped` + Docker sudah enabled.
- Dependensi berurutan dinyatakan eksplisit (`depends_on: service_healthy`) — facade menunggu ComfyUI benar-benar siap, bukan sekadar proses hidup.
- Isolasi: tiap layanan punya image sendiri, jadi memutakhirkan frontend tidak menyentuh engine.
- Port dan volume tercatat di satu tempat yang ikut ter-version.

### 4.5 Model di-mount, bukan dibakar ke image

16,4 GiB bobot model. Kalau dimasukkan ke image: setiap rebuild menggandakan pemakaian disk, dan mengganti kuantisasi berarti build ulang image besar. Dengan mount read-only, mengganti model hanya operasi file.

### 4.6 Facade mempertahankan kontrak API lama

Facade mengekspos `/v1/images/generations`, `/v1/images/edits`, `/health`, `/v1/system/load` — nama dan bentuk yang sama seperti server inference sebelumnya. Karena itu penggantian engine inference tidak menyentuh backend maupun frontend sama sekali. Penerjemahan ke ComfyUI terjadi seluruhnya di dalam facade.

### 4.7 Hanya LAN, tanpa tunnel

Cloudflare Tunnel dan Vercel ditinggalkan karena dua hal: tidak dibutuhkan (semua pengguna ada di kantor) dan bermasalah secara teknis — halaman HTTPS tidak boleh memanggil backend HTTP (mixed content), jadi tunnel justru menambah titik gagal.

Jalur itu ditutup penuh pada 2026-09-23: project Vercel lama dihapus, `frontend/vercel.json` dan endpoint `/api/tunnel-status` (sisa fitur auto-deteksi tunnel) ikut dibuang. Tidak ada lagi titik masuk dari luar jaringan kantor — satu-satunya cara membuka aplikasi adalah `http://192.168.2.142:5151` dari LAN. Kalau nanti perlu diakses dari luar, ingat syaratnya: backend harus ikut HTTPS, karena browser memblokir panggilan dari halaman HTTPS ke `http://192.168.2.142:8281`.

### 4.8 Inference diserialkan

Tiga lapis lock, semuanya menuju satu proses ComfyUI:

```
backend (_generation_lock) → facade (_inference_lock) → ComfyUI (satu proses)
```

Ini bukan kehati-hatian berlebihan: menjalankan dua generasi bersamaan di kartu 16 GB akan OOM, dan ComfyUI memang memproses satu graph pada satu waktu. Karena itu antrean dibuat eksplisit (batas 10 job global, HTTP 429 bila penuh) dan statusnya terlihat di UI — lebih baik daripada pengguna menunggu tanpa penjelasan.

---

## 5. Batasan yang diketahui

| Batasan | Nilai | Sebab |
|---|---|---|
| Resolusi maksimum | **1K (1024)** | 2K punya 4× token latent; sisa VRAM hanya ~2,5 GiB |
| Generasi bersamaan | **1** | Satu proses ComfyUI, VRAM 16 GB |
| Antrean global | **10 job** | Dibatasi backend; lebih dari itu HTTP 429 |
| Referensi per request | **10** | Batas grafis, bukan teknis |
| Teks kecil di dalam gambar | Sering kabur | Batas keras ~1 MP; solusinya overlay teks setelah generasi |
| Model idle | Unload setelah 1 jam | Membebaskan VRAM untuk proses lain |

---

## 6. Titik gagal dan pemulihannya

| Gejala | Penyebab yang paling mungkin | Tindakan |
|---|---|---|
| `unet_name ... not in []` | Folder `diffusion_models/` hilang di direktori model | Buat folder + symlink, `docker compose restart comfyui` |
| Facade balas 502 | ComfyUI belum siap atau mati | `docker compose logs comfyui`, cek healthcheck |
| Generasi pertama lambat (~50 detik) | Model belum dimuat | Normal; model termuat setelah satu job |
| VRAM habis / OOM | Proses lain memakai GPU 1, atau model 2K dipaksa | Cek `nvidia-smi`, pastikan `QWEN_MAX_RESOLUTION=1024` |
| Frontend menunjuk alamat mati | IP server berubah | Ubah `VITE_API_URL` di `deploy/docker/.env`, build ulang **hanya** frontend |
| Container tidak melihat GPU | NVIDIA Container Toolkit belum terpasang | Lihat catatan GPU di `deploy/docker/README.md` |

---

## 7. Kalau nanti perlu naik kapasitas

Urut dari yang paling murah:

1. **Dua instance ComfyUI** di dua GPU, dengan facade bertindak sebagai dispatcher. Ini satu-satunya jalur yang memanfaatkan GPU 0 yang sekarang menganggur — dan menuntut backend berhenti menyerialkan `_generation_lock`, karena kapasitasnya menjadi dua.
2. **Kartu dengan VRAM lebih besar** (24 GB+) untuk membuka 2K tanpa mengubah arsitektur.
3. **Ganti engine** ke stack yang mendukung multi-GPU sekaligus punya manajemen memori yang benar. Ini pekerjaan facade saja — kontrak API ke backend tetap.

Yang **bukan** jalur peningkatan: menambah GPU ke proses ComfyUI yang sama. Engine-nya tidak mendukung sharding.
