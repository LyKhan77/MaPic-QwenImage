# Project Overview

MaPic turns text prompts and reference images into production-quality visuals — running entirely on local hardware. Built on **GLM-Image** (9B AR + 7B diffusion decoder), it delivers text-to-image and multi-reference image-to-image generation with no cloud dependencies, no API costs, and no rate limits.

project references :
- `https://huggingface.co/zai-org/GLM-Image`
- `https://github.com/zai-org/GLM-Image`

=====================

# Current State - Update this Section for every CHANGES and UPDATES

## Architecture: GLM-Image Multi-GPU (2026-05-06)

- **Single model:** GLM-Image (9B AR + 7B diffusion decoder, local diffusers pipeline)
- **3-service stack:** Frontend (:5151) → Backend (:8181) → GLM-Image Server (:30000)
- **Removed:** Ollama service, Z.ai cloud service, model selector UI, idle timeout/monitor
- **Multi-reference support:** Up to 3 reference images for I2I generation
- **Hardware:** RTX 5080 (16GB) + RTX 5080 (16GB) + RTX 4090 (24GB) — triple GPU via `device_map="balanced"`
- **Memory:** `MAX_MEMORY={0: "15GiB", 1: "15GiB", 2: "23GiB", "cpu": "4GiB"}` — balanced for heterogeneous GPUs
- **8-bit Quantization:** `bitsandbytes` INT8 for transformer + vision_language_encoder — halves weight memory (~32 GB -> ~16 GB), needed because balanced split puts most weight on 2x 16 GB GPUs
- **VAE on GPU 2:** VAE placed on RTX 4090 (cuda:2) for native GPU encode/decode — no CPU roundtrips
- **AR sampling:** `temperature=0.9`, `top_p=0.75`, `do_sample=True` — set on `vision_language_encoder.generation_config` after model load
- **Configurable generation params:** `num_inference_steps` (20-75, default 50 T2I / 35 I2I), `guidance_scale` (1.0-5.0, default 1.5) — exposed via frontend UI sliders
- **torch.compile:** Transformer compiled with `reduce-overhead` mode for ~2-4x diffusion speedup
- **Optimizations:** VAE slicing + tiling, attention slicing (transformer), Flash SDP + mem-efficient SDP, `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:128`
- **Pre-flight checks:** Blackwell (sm_120) architecture validation, PCIe topology logging, per-GPU parameter distribution logging
- **Est. VRAM peak:** GPU 0: 9–12 GB | GPU 1: 9–12 GB | GPU 2: 14–20 GB | Supports up to 2048x2048
- **Inference server:** `glm_image_server/main.py` — thread pool executor, inference lock, no idle unload
- **Concurrency:** asyncio.Lock ensures 1 inference at a time; `run_in_executor` keeps event loop responsive

### Key Files
| File | Role |
|------|------|
| `glm_image_server/main.py` | Inference server (T2I + I2I, thread pool, 3-GPU bf16, torch.compile, VAE on GPU 2) |
| `backend/services/glm_image_service.py` | Backend service layer (retry logic, 4hr timeout) |
| `backend/config.py` | `GLM_IMAGE_API_URL` (default localhost:30000) |
| `start-app.sh` | Starts all 3 services (exports `PYTORCH_CUDA_ALLOC_CONF`) |


=====================

# Project Structure - Update this Section IF there's any CHANGES or UPDATES

```
MaPic/
├── AGENTS.md                          # Agent behavior guidelines & project state
├── API.md                             # API documentation
├── README.md                          # Human-facing project overview
├── CLAUDE.md                          # Claude-specific instructions
├── start-app.sh                       # Orchestrates all 3 services (Frontend + Backend + GLM-Image Server)
├── start-mapic-glm.sh                 # Standalone GLM-Image Server launcher
├── mapic-glm.service                  # systemd service file for GLM-Image Server
├── howto-systemctl.md                 # systemd setup instructions
│
├── backend/                           # FastAPI Backend (:8181)
│   ├── main.py                        # FastAPI app — API routes (/api/health, /api/generate, /api/history, etc.)
│   ├── schemas.py                     # Pydantic models — GenerateRequest, Generation
│   ├── config.py                      # Environment config loader (Supabase, CORS, GLM_IMAGE_API_URL)
│   ├── requirements.txt               # Python deps: fastapi, uvicorn, supabase, httpx, pydantic, Pillow
│   └── services/
│       ├── glm_image_service.py       # HTTP client to GLM-Image Server — retry logic, auto-load, 4hr timeout
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
│       │   ├── Login.tsx              # Supabase Auth UI login page (Google OAuth)
│       │   └── Dashboard.tsx          # Main app UI — orchestrates canvas, sidebar, prompt, model status
│       ├── components/
│       │   ├── ImageCanvas.tsx        # Displays generated image, download & copy actions
│       │   ├── PromptInput.tsx        # Prompt textarea + reference image upload (up to 3 images)
│       │   ├── Sidebar.tsx            # Collapsible sidebar — history list, new chat, theme toggle, logout
│       │   ├── ModelStatusBadge.tsx   # Shows model load/unload/ready status with load/unload actions
│       │   ├── Loader.tsx             # Animated loading spinner
│       │   └── BearAnimation.tsx      # Decorative idle animation component
│       ├── hooks/
│       │   └── useGenerationStatus.ts # Hook returning human-readable generation step text
│       └── lib/
│           ├── api.ts                 # Frontend API client — health, generate, history, load/unload
│           ├── supabase.ts            # Supabase JS client initialization (auth + DB)
│           └── utils.ts               # Utility helpers (cn — clsx + tailwind-merge)
│
├── glm_image_server/                  # Local AI Inference Server (:30000)
│   ├── main.py                        # FastAPI server wrapping GlmImagePipeline — T2I, I2I, load/unload, SSE progress
│   └── requirements.txt               # PyTorch (cu128), diffusers, transformers, accelerate, fastapi
│
└── test/                              # Screenshots & test images
```

### Data Flow
1. **User** → Frontend (`:5151`) submits prompt (+ optional reference images)
2. **Frontend** → Backend (`:8181`) `POST /api/generate` with prompt + base64 images
3. **Backend** → GLM-Image Server (`:30000`) `POST /v1/images/generations` or `/v1/images/edits`
4. **GLM-Image Server** runs `GlmImagePipeline` inference (3-GPU, bf16, torch.compile, VAE on GPU 2)
5. **Backend** receives base64 image → uploads to Supabase Storage → inserts record to PostgreSQL → returns Generation to Frontend
6. **Frontend** displays image and updates history sidebar


=====================

# IMPORTANT — DO NOT EDIT BELOW

This section contains critical agent behavior guidelines. Any changes require explicit user approval.

## Important Notes - Project RULES

- Always use relevant skills to help with tasks.
- Always ask the user if there are any plans or discussions that need to be validated.
- Always provide a summary after finishing a task.
- Always update `README.md` whenever there are changes to key features and the app's workflow.
- Commit every function change so you can roll back and view the code history in case of a malfunction or a failed change.
- Do not re-read files that have already been read in this session unless necessary.
- Minimize non-essential tool calls.

===========================

# CLAUDE.md

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
