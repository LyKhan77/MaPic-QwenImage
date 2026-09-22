# Dockerisasi MaPic (Qwen-Image 2.1) — Rancangan

> Menggantikan empat unit systemd (`comfyui`, `qwen-image`, `mapic-backend`, `mapic-frontend`) dengan satu compose project. Model tetap di disk host, tidak dibakar ke image.

**Target host:** `gspe-ai2` — Docker 29.6.2, Compose v5.3.1, NVIDIA runtime sudah terdaftar (`Runtimes: ... nvidia ...`), user `gspe-ai2` bisa menjalankan docker tanpa sudo.

**Kondisi awal yang wajib dihormati:** server ini menjalankan **31 compose project, 115 container, 50 GB image**. Project baru harus memakai nama dan network sendiri, dan tidak boleh menyentuh volume/image milik project lain.

---

## Keputusan rancangan

| Keputusan | Alasan |
|---|---|
| Base image `pytorch/pytorch:2.11.0-cuda13.0-cudnn9-runtime` | Torch-nya **identik** dengan yang terbukti jalan di host (2.11.0+cu130). Menghindari unduh torch ~2,5 GB dan risiko beda versi. Ukuran 3,01 GB. |
| Model **di-mount**, bukan di-`COPY` | Total 16,4 GiB. Di image akan menggandakan disk dan memperlambat setiap rebuild. Mount read-only + `extra_model_paths.yaml`. |
| ComfyUI **tanpa port publik** | Hanya facade yang perlu menjangkaunya, lewat network internal compose (`http://comfyui:8188`). Port host dibuka hanya di 127.0.0.1 untuk debugging. |
| Frontend multi-stage (`node` → `nginx:alpine`) | `nginx:alpine` sudah ada di lokal (62 MB). Menggantikan `spa_server.py` dengan fallback SPA bawaan nginx. |
| GPU dipin ke device 1 | GPU 0 pernah lepas dari bus (Xid 79/154). Konsisten dengan `CUDA_VISIBLE_DEVICES=1` yang sekarang. |
| Nama project `mapic` | Tidak bentrok dengan 31 project yang sudah ada. |

## Struktur file (di dalam repo, ikut ter-version)

```
deploy/docker/
├── docker-compose.yml
├── .env.example              # nilai contoh; .env asli tidak di-commit
├── comfyui/
│   ├── Dockerfile
│   └── extra_model_paths.yaml
├── qwen-image/Dockerfile
├── backend/Dockerfile
└── frontend/
    ├── Dockerfile
    └── nginx.conf
```

## Port yang dipakai

| Layanan | Host | Container | Catatan |
|---|---|---|---|
| frontend | `5151` | `80` | diakses browser kantor |
| backend | `8281` | `8000` | dipanggil browser; **8181 sudah terpakai project lain** |
| qwen-image | — | `30000` | hanya internal, tidak perlu diekspos |
| comfyui | `127.0.0.1:8188` | `8188` | hanya untuk debugging dari server |

---

## Komponen

### 1. `comfyui/Dockerfile`

```dockerfile
FROM pytorch/pytorch:2.11.0-cuda13.0-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_XET=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ffmpeg libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

ARG COMFYUI_COMMIT=e638023
ARG GGUF_NODE_COMMIT=edd981b

RUN git clone https://github.com/comfyanonymous/ComfyUI.git /opt/ComfyUI \
    && cd /opt/ComfyUI && git checkout ${COMFYUI_COMMIT} \
    && git clone https://github.com/leejet/ComfyUI-GGUF.git /opt/ComfyUI/custom_nodes/ComfyUI-GGUF \
    && cd /opt/ComfyUI/custom_nodes/ComfyUI-GGUF && git checkout ${GGUF_NODE_COMMIT}

WORKDIR /opt/ComfyUI
# torch dari base image tidak diunduh ulang; sisanya ~500 MB
RUN pip install -r requirements.txt && pip install gguf

COPY extra_model_paths.yaml /opt/ComfyUI/extra_model_paths.yaml
EXPOSE 8188
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188", \
     "--lowvram", "--extra-model-paths-config", "/opt/ComfyUI/extra_model_paths.yaml"]
```

### 2. `comfyui/extra_model_paths.yaml`

Satu mount read-only untuk seluruh model:

```yaml
mapic:
  base_path: /models
  diffusion_models: diffusion_models
  text_encoders: text_encoders
  vae: vae
```

### 3. `qwen-image/Dockerfile` (facade)

```dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY qwen_image_server/requirements-facade.txt .
RUN pip install --no-cache-dir -r requirements-facade.txt
COPY qwen_image_server/ /app/
EXPOSE 30000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "30000"]
```

`requirements-facade.txt` (baru, kecil — tanpa torch):

```
fastapi>=0.110
uvicorn>=0.29
httpx
websockets
pillow>=10.0
```

### 4. `backend/Dockerfile`

```dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /app/
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 5. `frontend/Dockerfile` + `nginx.conf`

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
ARG VITE_API_URL
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ENV VITE_API_URL=$VITE_API_URL \
    VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
```

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

> Vite menanam `VITE_*` saat **build**, bukan saat jalan. Kalau IP server berubah, image frontend harus di-build ulang.

### 6. `docker-compose.yml`

```yaml
name: mapic

services:
  comfyui:
    build:
      context: ../..
      dockerfile: deploy/docker/comfyui/Dockerfile
    restart: unless-stopped
    environment:
      - NVIDIA_VISIBLE_DEVICES=1
    volumes:
      - ${MODELS_DIR:-/home/gspe-ai2/apps/qwen21-gguf}:/models:ro
      - comfyui-input:/opt/ComfyUI/input
      - comfyui-output:/opt/ComfyUI/output
      - comfyui-temp:/opt/ComfyUI/temp
    ports:
      - "127.0.0.1:8188:8188"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              device_ids: ["1"]
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8188/system_stats"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 120s

  qwen-image:
    build:
      context: ../..
      dockerfile: deploy/docker/qwen-image/Dockerfile
    restart: unless-stopped
    environment:
      - COMFY_BASE_URL=http://comfyui:8188
      - QWEN_MAX_RESOLUTION=1024
      - PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:128
    depends_on:
      comfyui:
        condition: service_healthy

  backend:
    build:
      context: ../..
      dockerfile: deploy/docker/backend/Dockerfile
    restart: unless-stopped
    env_file: .env
    environment:
      - QWEN_IMAGE_API_URL=http://qwen-image:30000
      - QWEN_DEFAULT_RESOLUTION=1024
    ports:
      - "8281:8000"
    depends_on:
      - qwen-image

  frontend:
    build:
      context: ../..
      dockerfile: deploy/docker/frontend/Dockerfile
      args:
        VITE_API_URL: http://192.168.2.142:8281/api
        VITE_SUPABASE_URL: ${SUPABASE_URL}
        VITE_SUPABASE_ANON_KEY: ${SUPABASE_ANON_KEY}
    restart: unless-stopped
    ports:
      - "5151:80"
    depends_on:
      - backend

volumes:
  comfyui-input:
  comfyui-output:
  comfyui-temp:
```

---

## Urutan eksekusi

### Fase 1 — Build (tanpa mengganggu yang berjalan)

- [ ] `docker pull pytorch/pytorch:2.11.0-cuda13.0-cudnn9-runtime` — 3,01 GB, unduh sekali
- [ ] `docker compose build comfyui` (~500 MB dependensi tambahan)
- [ ] Verifikasi GPU di dalam image: `docker run --rm --gpus '"device=1"' --entrypoint nvidia-smi <image>`
- [ ] `docker compose build qwen-image backend frontend` (kecil; frontend mengunduh node deps ~200 MB)

### Fase 2 — Uji tanpa mematikan systemd (port bentrok sementara)

- [ ] Jalankan hanya `comfyui` + `qwen-image` di **port uji** (ubah sementara 8188→18188, 30000→30001) dan jalankan uji T2I 1K langsung ke facade — memastikan container bisa mengakses GPU dan model
- [ ] Bandingkan waktu generasi dengan baseline systemd (32 detik)

### Fase 3 — Cutover

- [ ] `sudo systemctl disable --now comfyui qwen-image mapic-backend mapic-frontend`
- [ ] `docker compose up -d`
- [ ] Verifikasi berurutan: `docker compose ps`, healthcheck comfyui, `/health` facade, `/api/health` backend, `curl http://192.168.2.142:5151/`
- [ ] Uji E2E: generate → tersimpan di Supabase → hapus

### Fase 4 — Setelah stabil

- [ ] Hapus unit systemd lama (atau biarkan disabled sebagai rollback)
- [ ] Perbarui `README.md`, `API.md`, `AGENTS.md`: cara menjalankan sekarang `docker compose up -d`, log lewat `docker compose logs -f`
- [ ] Catat image final dan cara rebuild

## Rollback

Unit systemd dibiarkan terpasang tapi `disabled`. Kalau ada masalah: `docker compose down`, lalu `sudo systemctl enable --now comfyui qwen-image mapic-backend mapic-frontend`. Volume Docker tidak menyimpan state penting, jadi tidak ada data yang hilang.

## Risiko

| Risiko | Dampak | Mitigasi |
|---|---|---|
| **Unduhan ~3,5 GB di jaringan flaky** | Build bisa 15–60 menit, atau gagal di tengah | `docker pull` base dulu sebelum build; BuildKit cache; ulangi build bila gagal — layer yang sudah jadi tidak diunduh ulang |
| Port 8188/30000 dipakai saat uji Fase 2 | Tabrakan dengan systemd | Pakai port uji berbeda (18188/30001) |
| IP server berubah | Frontend menunjuk alamat mati | Dokumentasikan bahwa `VITE_API_URL` ditanam saat build; rebuild image frontend |
| Container ikut naik saat boot sebelum Docker siap | ComfyUI gagal akses GPU | `restart: unless-stopped` + healthcheck; Docker sendiri sudah `enabled` di server ini |
| Disk image bertambah | ~7 GB (base 3 GB + layer build) | `docker system prune` berkala; jangan hapus image project lain |
