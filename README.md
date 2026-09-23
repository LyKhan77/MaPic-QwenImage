# MaPic - GenAI Image Studio

**Developed by Lee Khan** | *Synthesizing the Future*

MaPic turns text prompts and reference images into production-quality visuals with local Qwen-Image 2.1 inference. Seluruh stack berjalan di satu server kantor sebagai container Docker, jadi tidak ada biaya API, tidak ada rate limit, dan tidak ada trafik keluar jaringan.

## 🚀 Features

*   **AI Image Generation:** Generate images with Qwen-Image 2.1 (7B single-stream DiT + Qwen3-VL encoder) via ComfyUI + GGUF Q8_0.
*   **Multi-Reference Support:** Attach up to 10 reference images for image-to-image generation, style transfer, editing, and identity-preserving workflows.
*   **Transparent Output:** Menghasilkan RGBA dengan latar transparan. Output dikunci di **1K (1024×1024)** — 2K tidak muat di VRAM 16 GB.
*   **Berjalan di jaringan kantor:** Frontend, backend, dan inference semuanya container Docker di satu server. Tidak ada dependensi ke Vercel atau tunnel.
*   **Local GPU Inference:** The Qwen-Image 2.1 server runs locally on CUDA GPUs with no cloud inference cost or rate limit.
*   **Model Load Controls:** The UI can load and unload the model. The inference server also unloads from VRAM after 1 hour of inactivity.
*   **Generation Queue:** Users can submit another prompt while a generation is active by clicking **New Generation**. The active loading view stays read-only.
*   **Active Generation Recovery:** The active generation indicator shows queued/running/saving jobs, rehydrates the current user's active job view after refresh, and auto-focuses the latest finished result (including multi-queue completion order).
*   **Configurable Generation Params:** Frontend exposes `num_inference_steps`, True CFG scale (with negative prompt), and 1K/2K resolution.
*   **History Management:** Generated images and prompts are saved to Supabase and can be viewed, selected, or deleted.
*   **Secure Auth:** Google OAuth 2.0 via Supabase Authentication.
*   **Responsive UI:** Collapsible sidebar, dark/light mode, Framer Motion animations, and mobile-friendly layout.
*   **Share & Download:** Download images or copy direct public links.

## 🏗️ Architecture

### Alur (semua di jaringan kantor, di dalam Docker)

```
Browser kantor
    |
    +--> frontend :5151   (nginx, React SPA)
            |
            +--> backend :8281   (FastAPI — auth, riwayat, Supabase)
                    |
                    +--> qwen-image :30000   (facade, internal saja)
                            |
                            +--> comfyui :8188   (engine, GPU 1)
                                    |
                                    +--> GGUF Q8_0 di /models (mount read-only)
```

## 🌐 Deployment Saat Ini

Berjalan sepenuhnya di jaringan kantor, sebagai container Docker di `gspe-ai2`:

| Layanan | Alamat | Catatan |
|---------|--------|---------|
| Frontend | `http://192.168.2.142:5151` | nginx di container |
| Backend | `http://192.168.2.142:8281/api` | API yang dipanggil browser |
| Backend health | `http://192.168.2.142:8281/api/health` | Status rantai ke facade |
| ComfyUI | `127.0.0.1:8188` | Debug saja; dari komputer lain pakai SSH tunnel |

Vercel dan Cloudflare Tunnel **tidak lagi dipakai**. Bagian di bawah disimpan hanya sebagai rujukan historis bila nanti ingin mengekspos ke publik lagi — dan perlu diingat halaman HTTPS tidak bisa memanggil backend HTTP (mixed content), jadi tunnel/HTTPS tetap diperlukan untuk itu.

## 🛠️ Tech Stack

### Frontend
*   **Framework:** React 18 + Vite
*   **Styling:** Tailwind CSS
*   **Icons:** Lucide React
*   **State Management:** TanStack Query
*   **Animations:** Framer Motion
*   **Notifications:** Sonner
*   **Hosting:** Vercel

### Backend
*   **Framework:** Python FastAPI
*   **Database & Storage:** Supabase PostgreSQL + Storage
*   **Tunnel:** Cloudflare Tunnel to local `:8281`
*   **AI Service Client:** HTTP client to the Qwen-Image 2.1 server

### Inference Server
*   **Framework:** ComfyUI + ComfyUI-GGUF (bukan diffusers — lihat `deploy/docker/README.md` untuk alasannya)
*   **Model:** Qwen-Image 2.1 (`Qwen/Qwen-Image-2.1`) — 7B single-stream DiT + Qwen3-VL 8B encoder + 64-channel RGBA VAE
*   **Kuantisasi:** GGUF **Q8_0** (7,07 GiB) + text encoder int8 (8,71 GiB) + VAE bf16 (0,63 GiB)
*   **Runtime:** PyTorch 2.11 (CUDA 13.0), transformers 5.17, ComfyUI dengan `--lowvram`
*   **Hardware:** satu RTX 5080 16 GB cukup untuk 1K (VRAM puncak ~13,7 GB). GPU dipin lewat `NVIDIA_VISIBLE_DEVICES`.
*   **Batas:** `QWEN_MAX_RESOLUTION=1024`. 2K tidak muat — ruang sisa hanya ~2,5 GiB.
*   **Performa terukur (1K, 40 step):** T2I 32–34 s · CFG 2.0 63 s · I2I 1 referensi 50 s · I2I 3 referensi 84 s

## 📦 Installation & Setup

### Prerequisites
*   Node.js and npm
*   Python 3.10+
*   CUDA-capable NVIDIA GPUs
*   Supabase project with Auth, PostgreSQL, and Storage configured
*   `cloudflared` for production tunnel access
*   Vercel account/CLI for frontend deployment

### 1. Clone the Repository

```bash
git clone git@github.com:LyKhan77/MaPic-QwenImage.git
cd MaPic-QwenImage
```

### 2. Menjalankan stack (Docker)

Seluruh stack — ComfyUI, facade, backend, dan frontend — berjalan sebagai container:

```bash
cd deploy/docker
cp .env.example .env     # isi VITE_API_URL, SUPABASE_URL, SUPABASE_ANON_KEY
nano .env
docker compose up -d --build
docker compose ps
```

Bobot model **tidak** ikut ke dalam image: unduh ke `~/apps/qwen21-gguf`, lalu folder itu di-mount read-only. Tata letak folder yang diharapkan dan perintah operasional lainnya ada di [`deploy/docker/README.md`](deploy/docker/README.md).

### 3. Backend — rahasia runtime

`backend/.env` dibaca saat container jalan (lewat `env_file`):

```env
SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"
QWEN_DEFAULT_RESOLUTION="1024"
CORS_ORIGINS="http://localhost:5151,http://192.168.2.142:5151"
```

`QWEN_IMAGE_API_URL` tidak perlu diisi manual — compose menetapkannya ke `http://qwen-image:30000` di network internal.

### 4. Frontend — nilai build-time

`deploy/docker/.env` berisi nilai yang ditanam Vite saat build:

```env
VITE_API_URL=http://192.168.2.142:8281/api
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
```

Kalau IP server berubah, ubah di sini lalu rebuild **hanya** layanan frontend:

```bash
docker compose build frontend && docker compose up -d frontend
```

### 5. Alamat

Semua diakses dari jaringan kantor:

*   Frontend: `http://192.168.2.142:5151`
*   Backend: `http://192.168.2.142:8281/api`
*   ComfyUI (debug): SSH tunnel ke `127.0.0.1:8188`

Untuk mode pengembangan frontend (hot reload), jalankan terpisah di port berbeda — jangan bersamaan dengan container frontend:

```bash
cd frontend && VITE_API_URL=http://localhost:8281/api npm run dev -- --port 5152
```

## 🚢 (Historis) Production Frontend + Tunnel

> Sejak 2026-09-23 MaPic berjalan penuh di jaringan kantor lewat Docker. Vercel dan Cloudflare Tunnel tidak dipakai lagi; bab ini disimpan sebagai rujukan bila nanti ingin mengekspos ke publik lagi.

### Vercel Environment Variables

Set these in Vercel project settings for Production:

```env
VITE_API_URL=https://api.mapic-backend.site/api
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-key
```

`VITE_API_URL` must include the `/api` suffix because the backend routes are mounted under `/api`.

### Start Cloudflare Tunnel

```bash
cloudflared tunnel run mapic-backend
```

The named tunnel uses `api.mapic-backend.site` — a permanent URL that does not change on restart.

### Deploy Frontend

```bash
cd frontend
vercel --prod
```

The frontend is a static React SPA. `frontend/vercel.json` rewrites all routes to `index.html` for client-side routing.

## ✅ Health Checks

```bash
# Qwen-Image server
curl -s http://localhost:30000/health

# Backend local
curl -s http://localhost:8281/api/health

# Backend through tunnel
curl -s https://api.mapic-backend.site/api/health

# Verify tunnel reaches MaPic backend
curl -s https://api.mapic-backend.site/openapi.json \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['title'])"
# Expected: Mapic API
```

## 🖼️ Usage

1.  Open `https://mapic-glm.vercel.app` or local frontend `http://localhost:5151`.
2.  Login with Google through Supabase Auth.
3.  Type a prompt in the bottom prompt input.
4.  Optionally attach up to 10 reference images.
5.  Adjust inference steps, or True CFG scale with a negative prompt, if needed. Resolusi terkunci di 1K.
6.  Click **Generate** or press Enter.
7.  During generation, the loading view is read-only. Use **New Generation** to open a clean prompt and submit another request while the current job continues.
8.  Track queued/running/saving jobs in the active generation indicator, or click your active job to refocus the loader.
9.  Completed jobs open directly in the canvas, and prior generations remain available from the sidebar.

MaPic accepts a maximum of 10 active or queued generation requests globally. When capacity is full, new requests return HTTP 429 with a retry-later message.

## 🔧 Troubleshooting

Use [vercel-docs.md](vercel-docs.md) for detailed production troubleshooting.

Common checks:

*   If the frontend shows offline, verify the tunnel is running and `VITE_API_URL` points to the current tunnel URL.
*   If browser console shows CORS errors, confirm backend `CORS_ORIGINS` includes `https://mapic-glm.vercel.app`.
*   If the tunnel reaches the wrong app, check `~/.cloudflared/config.yml` and confirm ingress points to `http://localhost:8281`.
*   If Supabase login fails on Vercel, confirm Vercel env vars and Supabase redirect URLs include `https://mapic-glm.vercel.app`.
*   If model status is offline, check both `http://localhost:30000/health` and `http://localhost:8281/api/health`.

## ⚡ Creator

Developed with vision by **Lee Khan**.
*The code is the canvas.*
