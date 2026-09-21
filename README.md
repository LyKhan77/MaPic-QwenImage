# MaPic - GenAI Image Studio

**Developed by Lee Khan** | *Synthesizing the Future*

MaPic turns text prompts and reference images into production-quality visuals with local Qwen-Image 2.1 inference. The production frontend is deployed on Vercel, while the backend and GPU inference stack run on local hardware and are exposed to the frontend through Cloudflare Tunnel.

## 🚀 Features

*   **AI Image Generation:** Generate images with Qwen-Image 2.1 (7B single-stream DiT + Qwen3-VL encoder) using a local diffusers pipeline.
*   **Multi-Reference Support:** Attach up to 10 reference images for image-to-image generation, style transfer, editing, and identity-preserving workflows.
*   **Native 2K & Transparent Output:** Pick 1K or 2K output, and generate RGBA images with a transparent background.
*   **Production Frontend on Vercel:** React SPA is served from `https://mapic-glm.vercel.app`.
*   **Cloudflare Tunnel Backend Access:** Vercel frontend communicates with the local backend through a public tunnel URL.
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

### Production Flow

```
User Browser
    |
    +--> Vercel CDN (https://mapic-glm.vercel.app)
    |       Serves React SPA
    |
    +--> Cloudflare Edge --> Named Tunnel --> Local Backend :8181
            (https://api.mapic-backend.site)
                                              |
                                              +--> Qwen-Image Server :30000
                                                     |
                                                     +--> diffusers QwenImage21Pipeline
```

### Local Development Flow

```
Frontend (React/Vite :5151)
    |
    +--> MaPic Backend (FastAPI :8181)
            |
            +--> Qwen-Image Server (FastAPI :30000)
                    |
                    +--> Qwen-Image 2.1 local pipeline
```

## 🌐 Current Deployment

| Service | URL | Notes |
|---------|-----|-------|
| Frontend | `https://mapic-glm.vercel.app` | Vercel production app |
| Backend tunnel | `https://api.mapic-backend.site` | Named tunnel — permanent URL |
| Backend health | `https://api.mapic-backend.site/api/health` | Public health check through tunnel |
| Backend local | `http://localhost:8181/api/health` | Local backend health check |
| Qwen-Image local | `http://localhost:30000/health` | Local inference server health check |

For Vercel and Cloudflare Tunnel troubleshooting, see [vercel-docs.md](vercel-docs.md).

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
*   **Tunnel:** Cloudflare Tunnel to local `:8181`
*   **AI Service Client:** HTTP client to the Qwen-Image 2.1 server

### Inference Server
*   **Framework:** Python FastAPI + Uvicorn
*   **Model:** Qwen-Image 2.1 (`Qwen/Qwen-Image-2.1`, 7B single-stream DiT + Qwen3-VL 8B encoder + 64-channel RGBA VAE)
*   **Runtime:** PyTorch (CUDA 12.8), diffusers `QwenImage21Pipeline` (git main), transformers >= 5.17
*   **Hardware Target:** Multi-GPU NVIDIA; set `QWEN_MAX_MEMORY` per host, or `QWEN_CPU_OFFLOAD=1` for limited VRAM
*   **Optimizations:** Balanced device map, explicit `MAX_MEMORY`, VAE slicing/tiling, Flash SDP, memory-efficient SDP, prefix KV cache reuse
*   **Note:** `torch.compile` is currently disabled in code to preserve VRAM for activations.

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

### 2. Qwen-Image 2.1 Server Setup

```bash
cd qwen_image_server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start the server:

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 30000
```

The first model load downloads Qwen-Image 2.1 weights from Hugging Face (~47 GB). Before deploying on a new host, run `python smoke_test.py --resolution 2048` to measure peak VRAM and generation time for that machine.

### 3. Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env`:

```env
SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"
QWEN_IMAGE_API_URL="http://localhost:30000"
QWEN_DEFAULT_RESOLUTION="2048"
CORS_ORIGINS="http://localhost:5151,http://localhost:5152,https://mapic-glm.vercel.app"
```

Start the backend:

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8181 --reload
```

### 4. Frontend Setup

```bash
cd frontend
npm install
```

Create `frontend/.env` for local development:

```env
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-key
VITE_API_URL=http://localhost:8181/api
```

Run locally:

```bash
npm run dev
```

Local URLs:
*   Frontend: `http://localhost:5151`
*   Backend: `http://localhost:8181`
*   Qwen-Image Server: `http://localhost:30000`

### 5. Start All Local Services

From project root:

```bash
bash start-app.sh
```

This starts the Qwen-Image 2.1 server, backend, and local Vite frontend. In production, the frontend is served by Vercel, so the local Vite frontend is optional.

## 🚢 Production Frontend + Tunnel

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
curl -s http://localhost:8181/api/health

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
5.  Adjust inference steps, True CFG scale with a negative prompt, or the 1K/2K resolution if needed.
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
*   If the tunnel reaches the wrong app, check `~/.cloudflared/config.yml` and confirm ingress points to `http://localhost:8181`.
*   If Supabase login fails on Vercel, confirm Vercel env vars and Supabase redirect URLs include `https://mapic-glm.vercel.app`.
*   If model status is offline, check both `http://localhost:30000/health` and `http://localhost:8181/api/health`.

## ⚡ Creator

Developed with vision by **Lee Khan**.
*The code is the canvas.*
