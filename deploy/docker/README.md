# MaPic — Deployment Docker

Empat layanan, masing-masing satu folder dengan Dockerfile sendiri:

| Layanan | Folder | Port host | Isi image |
|---|---|---|---|
| `comfyui` | `comfyui/` | `127.0.0.1:8188` | Base PyTorch + ComfyUI + ComfyUI-GGUF. **Model di-mount, bukan dibakar.** |
| `qwen-image` | `qwen-image/` | — (internal) | Facade FastAPI yang menerjemahkan request jadi graph ComfyUI |
| `backend` | `backend/` | `8281` | API produk: auth, riwayat, Supabase |
| `frontend` | `frontend/` | `5151` | Build Vite → disajikan nginx |

Model tetap tinggal di host (`~/apps/qwen21-gguf`) dan di-mount read-only. Mengganti kuantisasi cukup dengan menukar file di folder itu, tanpa build ulang.

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

`comfyui` dipin ke **GPU 1** lewat `deploy.resources.reservations.devices`. GPU 0 tidak dipakai karena pernah lepas dari bus PCIe (Xid 79/154).

Bila compose di host ini mengabaikan blok `deploy`, ganti dengan cara runtime:

```yaml
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=1
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
