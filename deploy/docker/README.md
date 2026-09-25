# MaPic — Deployment Docker

Empat layanan, masing-masing satu folder dengan Dockerfile sendiri:

| Layanan | Folder | Port host | Isi image |
|---|---|---|---|
| `comfyui` | `comfyui/` | `127.0.0.1:8188` | Base PyTorch + ComfyUI + ComfyUI-GGUF. **Model di-mount, bukan dibakar.** |
| `qwen-image` | `qwen-image/` | — (internal) | Facade FastAPI yang menerjemahkan request jadi graph ComfyUI |
| `backend` | `backend/` | `8281` | API produk: auth, riwayat, Supabase |
| `frontend` | `frontend/` | `5151` | Build Vite → disajikan nginx |

Model tetap tinggal di host (`~/apps/qwen21-gguf`) dan di-mount read-only. Mengganti kuantisasi cukup dengan menukar file di folder itu, tanpa build ulang.

Bobot cutout Remove Background juga tinggal di host, terpisah dari model Qwen:

```
~/apps/mapic-rembg/models/isnet-general-use/isnet-general-use.onnx
```

Folder itu di-mount read-only ke container `backend` sebagai `/models` (`REMBG_HOME=/models`). Tanpa folder tersebut, endpoint cutout mengembalikan `503` sementara jalur Generate tetap normal. Unduhan otomatis saat request sengaja dimatikan.

## Struktur folder model

ComfyUI memindai folder berdasarkan `comfyui/extra_model_paths.yaml`. Tata letak yang diharapkan:

```
~/apps/qwen21-gguf/                 → di-mount sebagai /models (read-only)
├── diffusion_models/
│   └── qwen-image-2.1-Q8_0.gguf    → boleh symlink ke file di luar folder
├── text_encoders/
│   └── qwen3vl_8b_int8_convrot.safetensors
└── vae/
    └── qwen_image_2.1_vae_bf16.safetensors
```

`diffusion_models/` mudah terlewat: tanpa folder itu, ComfyUI mengembalikan daftar kosong dan facade akan melaporkan `unet_name ... not in []`. Kalau file GGUF berada di lokasi lain, cukup buat symlink:

```bash
mkdir -p ~/apps/qwen21-gguf/diffusion_models
ln -sfn ../qwen-image-2.1-Q8_0.gguf ~/apps/qwen21-gguf/diffusion_models/
docker compose restart comfyui    # folder dipindai saat start
```

## Menjalankan

```bash
cd ~/apps/mapic-qwen/deploy/docker
docker compose up -d --build
docker compose ps
```

Pertama kali membutuhkan unduhan base image ~3 GB. Pantau:

```bash
docker compose logs -f comfyui     # tunggu sampai healthcheck hijau
```

## Konfigurasi

Dua sumber, dipisah berdasarkan kebutuhannya:

| File | Untuk | Isi |
|---|---|---|
| `deploy/docker/.env` | **Build-time** frontend | `VITE_API_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY` |
| `backend/.env` | **Runtime** backend | `SUPABASE_SERVICE_ROLE_KEY` (rahasia), CORS |

Salin `.env.example` menjadi `.env` dan isi nilainya:

```bash
cp .env.example .env && nano .env
```

> `VITE_*` ditanam ke bundle saat build. Kalau IP server berubah, perbarui `.env` lalu build ulang hanya frontend (lihat di bawah).

## Perubahan yang sering dilakukan

**Ganti port** — ubah baris `ports:` layanan terkait di `docker-compose.yml`, lalu `docker compose up -d`.

**Ganti model atau kuantisasi** — taruh file baru di `~/apps/qwen21-gguf/`, lalu ubah `QWEN_GGUF_NAME` (atau `QWEN_CLIP_NAME` / `QWEN_VAE_NAME`) pada layanan `qwen-image` di `docker-compose.yml`, dan `docker compose up -d qwen-image`. Tidak perlu build ulang image apa pun.

**Aktifkan 2K** — set `QWEN_MAX_RESOLUTION: "2048"` pada `qwen-image`, dan longgarkan `frontend` (selector resolusi saat ini disembunyikan).

**Ganti CORS** — `backend/.env`, lalu `docker compose restart backend`.

## Rebuild hanya satu layanan

Ini keuntungan utama pemisahan per folder — tidak perlu menyentuh yang lain:

```bash
docker compose build frontend && docker compose up -d frontend
docker compose build backend  && docker compose up -d backend
docker compose build qwen-image && docker compose up -d qwen-image
```

Frontend wajib di-rebuild kalau `.env` berubah; backend dan facade cukup di-restart karena konfigurasinya dibaca saat jalan.

## Operasional

```bash
docker compose ps                       # status + healthcheck
docker compose logs -f qwen-image       # log satu layanan
docker compose restart backend          # restart tanpa rebuild
docker compose down                     # hentikan semua (model tetap di host)
docker compose down -v                  # + hapus volume ComfyUI (output/input/temp)
```

Melihat hasil gambar di dalam container:

```bash
docker compose exec comfyui ls -la /opt/ComfyUI/output
```

Membuka UI graph ComfyUI dari komputer Anda:

```bash
ssh -L 8188:127.0.0.1:8188 gspe-ai2@192.168.2.142
# lalu buka http://localhost:8188
```

## Catatan GPU

`comfyui` dipin ke **GPU 1** lewat `runtime: nvidia` + `NVIDIA_VISIBLE_DEVICES=1`. GPU 0 tidak dipakai karena pernah lepas dari bus PCIe (Xid 79/154).

Jalur runtime dipilih karena Docker di host ini memakai CDI untuk `--gpus` dan vendor spec-nya belum lengkap, sementara `daemon.json` sudah memuat entri runtime `nvidia` sehingga jalur ini langsung bekerja.

> **Jangan me-restart daemon Docker** untuk memperbaikinya. `live-restore` tidak aktif di `daemon.json`, jadi restart akan menghentikan seluruh ~115 container milik project lain di server ini.

Kalau nanti CDI diperbaiki (`sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml`), bentuk berikut bisa dipakai sebagai gantinya:

```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              device_ids: ["1"]
              capabilities: [gpu]
```

Verifikasi cepat bahwa container benar-benar melihat GPU:

```bash
docker run --rm --gpus '"device=1"' --entrypoint nvidia-smi mapic/comfyui:qwen21
```

## Kembali ke systemd (rollback)

Unit systemd lama sengaja dibiarkan terpasang tapi `disabled`:

```bash
docker compose down
sudo systemctl enable --now comfyui qwen-image mapic-backend mapic-frontend
```

Jangan jalankan keduanya bersamaan — port dan VRAM akan bentrok.

> `start-app.sh` di root repo juga memakai port **5151**, jadi ia akan bentrok dengan container `frontend`. Jalankan salah satu saja: stack Docker (`docker compose up -d`) atau skrip dev itu, bukan keduanya.
