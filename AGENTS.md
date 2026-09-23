# Project Overview

MaPic turns text prompts and reference images into production-quality visuals — running entirely on local hardware. Built on **Qwen-Image 2.1** (7B single-stream DiT + Qwen3-VL 8B encoder + 64-channel RGBA VAE), it delivers text-to-image and up to 10-reference image-to-image generation at 1K with no cloud dependencies, no API costs, and no rate limits.

project references :
- `https://huggingface.co/Qwen/Qwen-Image-2.1`
- `https://github.com/QwenLM/Qwen-Image-2.1`

=====================

# Current State - Update this Section for every CHANGES and UPDATES
## Architecture: Qwen-Image 2.1 + ComfyUI GGUF, di Docker (2026-09-23)

- **Single model:** Qwen-Image 2.1 (`Qwen/Qwen-Image-2.1`) — 7B single-stream DiT (32 layer, block-causal attention) + Qwen3-VL 8B text/vision encoder + 64-channel RGBA VAE.
- **Engine: ComfyUI + ComfyUI-GGUF**, bukan diffusers. Kuantisasi **Q8_0** (7,07 GiB) + text encoder int8 (8,71 GiB) + VAE bf16 (0,63 GiB). Jalur diffusers sudah dicoba dan gagal di host ini: spill ke CPU memicu device mismatch di text encoder, 8-bit menaruh encoder di device `meta`, dan bf16 penuh OOM. ComfyUI berhasil karena *dynamic VRAM loading* memuat ketiga komponen bergantian, bukan bersamaan.
- **Deployment: Docker Compose** (`deploy/docker/docker-compose.yml`) — 4 container: `comfyui`, `qwen-image` (facade), `backend`, `frontend`. Unit systemd lama sudah `disabled` tetapi masih terpasang sebagai rollback.
- **Port:** frontend `5151` → backend `8281` → facade `30000` (internal saja) → comfyui `127.0.0.1:8188` (debug saja). **`8181` tidak dipakai** karena sudah terisi project lain di server.
- **GPU:** dipin ke **device 1** lewat `runtime: nvidia` + `NVIDIA_VISIBLE_DEVICES=1`. GPU 0 sengaja tidak dipakai karena pernah lepas dari bus PCIe (Xid 79/154). Docker di server memakai CDI yang vendor spec-nya belum lengkap, jadi jalur `runtime:` dipilih agar tidak perlu restart daemon — restart akan mematikan seluruh container project lain di server itu.
- **Batas resolusi:** `QWEN_MAX_RESOLUTION=1024`. 2K tidak muat: sisa VRAM hanya ~2,5 GiB sementara 2048² punya 4× token latent.
- **Performa terukur (1K, 40 step):** T2I 32–34 s · CFG 2.0 63 s · I2I 1 referensi 50 s · I2I 3 referensi 84 s · VRAM puncak ~13,7 GB di **satu** kartu.
- **Multi-reference:** sampai 10 gambar untuk I2I.
- **Guidance:** default tanpa guidance. `true_cfg_scale > 1` hanya aktif bersama negative prompt, dan menggandakan waktu per step.
- **Rendering teks:** penungkit terbesarnya **disiplin prompt** (teks persis dalam tanda kutip, pendek, tipografi + posisi eksplisit), bukan setting. 60 step justru memunculkan artefak. Batas kerasnya resolusi 1 MP — teks kecil akan selalu kabur, perlu overlay setelah generasi.
- **Concurrency:** satu generasi pada satu waktu — backend (`_generation_lock`) → facade (`_inference_lock`) → satu proses ComfyUI. Kapasitas 10 job antre global (HTTP 429 bila penuh).
- **Configurable generation params:** `num_inference_steps` (20-75, default 40), `true_cfg_scale` (1.0-3.0, default 1.0 = guidance off, butuh negative prompt) — lewat modal settings frontend. Selector resolusi sudah disembunyikan karena host ini 1K saja.
- **Frontend:** input di bar bawah otomatis membawa prompt + gambar hasil sebagai referensi sehingga iterasi I2I jalan dari UI. Modal settings di-portal ke `document.body` karena `backdrop-filter` pada root-nya menjadikan elemen itu containing block untuk `position: fixed`.
- **Docs deploy:** `deploy/docker/README.md` — operasional, struktur folder model, catatan GPU, dan cara rebuild per layanan.
- **Jalur publik ditutup (2026-09-23):** project Vercel lama dihapus, `frontend/vercel.json` dan endpoint `/api/tunnel-status` ikut dibuang. Tidak ada titik masuk dari luar jaringan kantor; akses hanya `http://192.168.2.142:5151`. Mengembalikannya menuntut HTTPS di backend juga, karena browser memblokir halaman HTTPS yang memanggil backend HTTP.
- **Auth API (2026-09-23):** semua endpoint backend kecuali `GET /api/health` menuntut `Authorization: Bearer <access token Supabase>`. Backend memverifikasi tanda tangan lewat JWKS project (ES256) dengan dependency `require_user` (`backend/auth.py`) dan memakai claim `sub` sebagai identitas — `user_id` dari body/URL tidak lagi dipercaya (`user_id` dihapus dari `GenerateRequest`, riwayat & hapus dibatasi ke pemilik token). Endpoint `/api/load/stream` (SSE) dihapus karena `EventSource` tidak bisa mengirim header; progres load dibaca lewat `GET /api/load/state`. Login UI: email + password, Google dinonaktifkan.

### Key Files
| File | Role |
|------|------|
| `deploy/docker/docker-compose.yml` | Definisi 4 layanan, port, volume, dan pinning GPU |
| `deploy/docker/README.md` | Operasional Docker: start/stop, log, rebuild per layanan, rollback |
| `qwen_image_server/main.py` | Facade: mempertahankan kontrak API lama, menerjemahkan request jadi graph ComfyUI |
| `qwen_image_server/comfy_client.py` | Klien HTTP + WebSocket ke ComfyUI (submit, progres, ambil hasil, upload referensi) |
| `qwen_image_server/workflows.py` | Penyusun graph API-format untuk T2I dan I2I (1-10 referensi) |
| `qwen_image_server/smoke_test.py` | Uji VRAM/timing untuk host baru (jalur diffusers, disimpan sebagai rujukan) |
| `backend/services/qwen_image_service.py` | Klien backend → facade (retry, auto-load, timeout 1 jam, penerusan pesan error) |
| `backend/config.py` | `QWEN_IMAGE_API_URL` (default localhost:30000), `QWEN_DEFAULT_RESOLUTION` |
| `start-app.sh` | Menjalankan stack Docker (bukan lagi menyalakan service sendiri) |


=====================

# Project Structure - Update this Section IF there's any CHANGES or UPDATES

```
MaPic/
├── AGENTS.md                          # Agent behavior guidelines & project state
├── ARCHITECTURE.md                    # Desain sistem, tanggung jawab komponen, alasan keputusan
├── WORKFLOW.md                        # Alur generasi, alur pengembangan, runbook
├── API.md                             # API documentation
├── database-schema.md                 # Skema Supabase (diverifikasi lewat introspeksi live)
├── README.md                          # Human-facing project overview
├── CLAUDE.md                          # Claude-specific instructions
├── start-app.sh                       # Menjalankan stack Docker (delegasi ke deploy/docker)
│
├── deploy/docker/                     # Deployment Docker (menggantikan systemd)
│   ├── docker-compose.yml             # 4 layanan: comfyui, qwen-image, backend, frontend
│   ├── comfyui/                       # Dockerfile engine + extra_model_paths.yaml
│   ├── qwen-image/                    # Dockerfile facade (tanpa torch, image kecil)
│   ├── backend/                       # Dockerfile API produk
│   ├── frontend/                      # Dockerfile multi-stage vite → nginx + nginx.conf
│   └── README.md                      # Operasional, struktur folder model, catatan GPU
│
├── backend/                           # FastAPI Backend (:8281 di host, :8000 di container)
│   ├── main.py                        # FastAPI app — API routes (/api/health, /api/generate, /api/history, etc.)
│   ├── schemas.py                     # Pydantic models — GenerateRequest, Generation
│   ├── config.py                      # Environment config loader (Supabase, CORS, QWEN_IMAGE_API_URL)
│   ├── requirements.txt               # Python deps: fastapi, uvicorn, supabase, httpx, pydantic, Pillow
│   └── services/
│       ├── qwen_image_service.py      # HTTP client to Qwen-Image Server — retry logic, auto-load, 1hr timeout
│       └── supabase_service.py        # Supabase DB & Storage ops — upload, insert, fetch, delete generations
│
├── frontend/                          # React + Vite Frontend (:5151)
│   ├── package.json                   # npm deps: React, Tailwind, Framer Motion, TanStack Query, Sonner, Lucide
│   ├── vite.config.ts                 # Vite build config
│   ├── tailwind.config.js             # Tailwind CSS theming (dark/light mode)
│   ├── index.html                     # HTML entry point
│   ├── public/                        # Static assets (logos, icons, demo images)
│   └── src/
│       ├── App.tsx                    # Root component — routing, auth session guard, login redirect
│       ├── main.tsx                   # React DOM mount
│       ├── types.ts                   # Shared TypeScript interfaces (Generation)
│       ├── index.css                  # Global styles + Tailwind directives
│       ├── pages/
│       │   ├── Login.tsx              # Login email + password lewat Supabase Auth
│       │   └── Dashboard.tsx          # Main app UI — orchestrates canvas, sidebar, prompt, model status
│       ├── components/
│       │   ├── ImageCanvas.tsx        # Displays generated image, download & copy actions
│       │   ├── PromptInput.tsx        # Prompt textarea + reference image upload (up to 10 images)
│       │   ├── Sidebar.tsx            # Collapsible sidebar — history list, new chat, theme toggle, logout
│       │   ├── ModelStatusBadge.tsx   # Shows model load/unload/ready status with load/unload actions
│       │   ├── GenerationStageBadge.tsx # Real-time generation stage list (top-right)
│       │   ├── GenerationTimeDisplay.tsx # Estimasi waktu proses dari stage + step saat ini
│       │   ├── ActiveGenerationsIndicator.tsx # Bottom-right global active gen pill (queue, other users)
│       │   ├── Loader.tsx             # Animated loading spinner
│       │   └── BearAnimation.tsx      # Decorative idle animation component
│       ├── hooks/
│       │   └── useGenerationStatus.ts # Hook returning human-readable generation step text
│       └── lib/
│           ├── api.ts                 # Frontend API client — health, generate, history, load/unload
│           ├── activeGenerationState.ts # Aturan kapan loader aktif / job dianggap selesai
│           ├── generation.ts          # Estimasi durasi generasi per stage
│           ├── supabase.ts            # Supabase JS client initialization (auth + DB)
│           └── utils.ts               # Utility helpers (cn — clsx + tailwind-merge)
│
├── qwen_image_server/                 # Facade inference (:30000, internal di Docker)
│   ├── main.py                        # FastAPI facade — mempertahankan kontrak API lama, menerjemahkan ke graph ComfyUI
│   ├── comfy_client.py                # Klien HTTP + WebSocket ke ComfyUI (submit, progres per node, ambil hasil)
│   ├── workflows.py                   # Penyusun graph API-format: T2I dan I2I (1-10 referensi)
│   ├── smoke_test.py                  # Uji VRAM/timing untuk host baru
│   ├── requirements-facade.txt        # Deps facade untuk image Docker (tanpa torch)
│   └── requirements.txt               # Deps jalur diffusers (disimpan sebagai rujukan)
│
└── temp/                              # Artefak lokal (uji A/B, backup, log) — diabaikan git
```

### Data Flow
1. **User** → Frontend (`:5151`, nginx) mengirim prompt (+ gambar referensi opsional)
2. **Frontend** → Backend (`:8281`) `POST /api/generate` dengan prompt + gambar base64
3. **Backend** → facade (`:30000`) `POST /v1/images/generations` atau `/v1/images/edits`
4. **Facade** menyusun graph ComfyUI (node GGUF + CLIP + VAE + sampler) lalu mengirim ke `comfyui:8188` lewat network internal Docker
5. **ComfyUI** menjalankan Qwen-Image 2.1 GGUF di GPU 1 dengan dynamic VRAM loading
6. **Backend** menerima PNG → upload ke Supabase Storage → insert record → mengembalikan `Generation`
7. **Frontend** menampilkan gambar dan memperbarui riwayat


=====================

# IMPORTANT — DO NOT EDIT BELOW

This section contains critical agent behavior guidelines. Any changes require explicit user approval.

## Important Notes - Project RULES

- **No AI attribution anywhere.** Do NOT add `Co-Authored-By: Claude ...`,
  `Generated with Claude Code`, or any AI/assistant attribution to commit messages,
  PR descriptions, code comments, or docs. Every contribution is recorded under the
  repo owner (the user) ONLY. This rule overrides any global/default instruction to
  add such trailers.
- Always use relevant skills to help with tasks.
- Always ask the user if there are any plans or discussions that need to be validated.
- Always provide a summary after finishing a task.
- Always update core documentation whenever there are changes to key features and the
  app's workflow.
- Commit every function change so you can roll back and view the code history in case
  of a malfunction or a failed change. Also UPDATE the `.gitignore` file whenever a new
  file is added that needs to be excluded before committing.
- Do not re-read files that have already been read in this session unless necessary.
- Minimize non-essential tool calls.
- For any new feature or discussion where the update is outside the context, be sure to
  propose creating a new branch.
- Save every plan or specification to the `docs\superpowers\plans` and
  `docs\superpowers\specs` folder so you can track which plans have been created or are
  currently being created. This allows you to resume the session if the AI agent's token
  expires. USE `Superpowers` skill to provide the plan. REMEMBER This file does not need
  to be updated unless requested. It is intended solely as a record of past information.
  Make sure not to DUPLICATE it; if you've already created a plan outside of Superpowers,
  there's no need to create another one, and vice versa.

===========================

# AGENTS.md — DO NOT EDIT BELOW

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
