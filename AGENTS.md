# Project Overview

MaPic turns text prompts and reference images into production-quality visuals — running entirely on local hardware. Built on **Qwen-Image 2.1** (7B single-stream DiT + Qwen3-VL 8B encoder + 64-channel RGBA VAE), it delivers text-to-image and up to 10-reference image-to-image generation at 1K/2K with no cloud dependencies, no API costs, and no rate limits.

project references :
- `https://huggingface.co/Qwen/Qwen-Image-2.1`
- `https://github.com/QwenLM/Qwen-Image-2.1`

=====================

# Current State - Update this Section for every CHANGES and UPDATES
## Architecture: Qwen-Image 2.1 Multi-GPU (2026-09-21)

- **Single model:** Qwen-Image 2.1 (`Qwen/Qwen-Image-2.1`) — 7B single-stream DiT (32 layers, block-causal attention) + Qwen3-VL 8B text/vision encoder + 64-channel RGBA VAE, via `QwenImage21Pipeline`.
- **3-service stack:** Frontend (:5151) → Backend (:8181) → Qwen-Image Server (:30000)
- **Removed:** Ollama service, Z.ai cloud service, model selector UI, AR sampling stage
- **Multi-reference support:** Up to 10 reference images for I2I generation
- **Hardware:** checked per host via `qwen_image_server/smoke_test.py`; no assumption carried over from the GLM-Image tri-GPU box
- **Memory & Sharding:** `QWEN_MAX_MEMORY` (default `{"cpu": "8GiB"}`) drives accelerate's `device_map="balanced"`; `QWEN_CPU_OFFLOAD=1` switches to CPU offload for low-VRAM hosts; `QWEN_MAX_RESOLUTION` caps output (default 2048).
- **Quantization:** none — bf16 weights. 8-bit via `PipelineQuantizationConfig` is not validated for this pipeline.
- **Guidance:** Qwen-Image 2.1 samples without guidance by default. `true_cfg_scale > 1` activates CFG only together with a negative prompt, and doubles the work per step.
- **Configurable generation params:** `num_inference_steps` (20-75, default 40), `true_cfg_scale` (1.0-3.0, default 1.0 = guidance off, needs a negative prompt), and resolution 1K/2K — exposed via the frontend settings modal
- **torch.compile:** disabled in code to preserve VRAM for activations
- **Optimizations:** VAE slicing + tiling, Flash SDP + mem-efficient SDP, prefix KV cache reuse, `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:128`
- **Pre-flight checks:** Blackwell (sm_120) architecture validation, PCIe topology logging, per-GPU parameter distribution logging
- **Est. VRAM peak:** measured per host with `qwen_image_server/smoke_test.py`; 1K fits comfortably on a single 24 GB GPU, 2K needs either more headroom or `QWEN_CPU_OFFLOAD=1`
- **Inference server:** `qwen_image_server/main.py` — thread pool executor, inference lock, no idle unload
- **Concurrency:** asyncio.Lock ensures 1 inference at a time; `run_in_executor` keeps event loop responsive
- **Generation queue UX:** Loading screen is read-only and shows no prompt input; users click New Generation during active work to open one clean prompt input and submit additional backend-queued jobs. Completed current-user jobs automatically open their result canvas with latest-finished priority, including after refresh-time active job recovery.
- **Global generation capacity:** Backend rejects new `/api/generate` requests with HTTP 429 when 10 active/accepted generation jobs are already in memory across all users.
- **Active generations indicator:** Bottom-right floating pill (`ActiveGenerationsIndicator`) polls global active jobs for every user, shows all in-flight generations across users, includes multiple jobs per user and a `/10` global capacity count, and rehydrates the current user's active generation view after refresh. User's own entries are clickable to refocus the canvas; others are view-only. Queued jobs show `queued` instead of a running timer.
- **Backend active tracking:** `GET /api/generations/active` returns in-memory tracked jobs with `queued` / `running` / `saving` status, elapsed time, inference step count, and reference image count. Generation elapsed time starts only after a job acquires the backend generation lock and begins the Qwen-Image request.
- **Model status badge (segment-based):** 4-segment pipeline (Pre-flight → Weights → Optimize → Finalize) replaces circular progress ring. Segment progress persisted via `GET /v1/system/load/state` (Qwen-Image) → `GET /api/load/state` (backend proxy). Frontend recovers loading state on page refresh.
- **Inference stage tracking:** `warmup → encoding → diffusion → decoding` — the diffusion stage is reported by the step callback. Qwen-Image 2.1 has no autoregressive stage, so `ar_sampling` is gone.
- **Shared generation util:** `estimateTotalSeconds()` extracted to `frontend/src/lib/generation.ts` — used by both `GenerationStageBadge` and `GenerationTimeDisplay`.
- **Configurable generation params:** `num_inference_steps` (20-75, default 40), `true_cfg_scale` (1.0-3.0, default 1.0 = guidance off, needs a negative prompt), and resolution 1K/2K — exposed via the frontend settings modal
- **torch.compile:** disabled in code to preserve VRAM for activations
- **Optimizations:** VAE slicing + tiling, Flash SDP + mem-efficient SDP, prefix KV cache reuse, `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:128`
- **Pre-flight checks:** Blackwell (sm_120) architecture validation, PCIe topology logging, per-GPU parameter distribution logging
- **Est. VRAM peak:** host-dependent; recorded after `qwen_image_server/smoke_test.py` runs on the target server and filled into the migration plan's calibration table
- **Inference server:** `qwen_image_server/main.py` — thread pool executor, inference lock, no idle unload
- **Concurrency:** asyncio.Lock ensures 1 inference at a time; `run_in_executor` keeps event loop responsive

### Key Files
| File | Role |
|------|------|
| `qwen_image_server/main.py` | Inference server (T2I + I2I, thread pool, bf16, `device_map=balanced` or CPU offload) |
| `qwen_image_server/smoke_test.py` | Standalone VRAM/timing check to run on any new host |
| `backend/services/qwen_image_service.py` | Backend service layer (retry logic, 1hr timeout, load state proxy) |
| `backend/config.py` | `QWEN_IMAGE_API_URL` (default localhost:30000), `QWEN_DEFAULT_RESOLUTION` |
| `start-app.sh` | Starts all 3 services (exports `PYTORCH_CUDA_ALLOC_CONF`) |


=====================

# Project Structure - Update this Section IF there's any CHANGES or UPDATES

```
MaPic/
├── AGENTS.md                          # Agent behavior guidelines & project state
├── API.md                             # API documentation
├── README.md                          # Human-facing project overview
├── CLAUDE.md                          # Claude-specific instructions
├── start-app.sh                       # Orchestrates all 3 services (Frontend + Backend + Qwen-Image Server)
│
├── backend/                           # FastAPI Backend (:8181)
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
│       │   ├── Login.tsx              # Supabase Auth UI login page (Google OAuth)
│       │   └── Dashboard.tsx          # Main app UI — orchestrates canvas, sidebar, prompt, model status
│       ├── components/
│       │   ├── ImageCanvas.tsx        # Displays generated image, download & copy actions
│       │   ├── PromptInput.tsx        # Prompt textarea + reference image upload (up to 3 images)
│       │   ├── Sidebar.tsx            # Collapsible sidebar — history list, new chat, theme toggle, logout
│       │   ├── ModelStatusBadge.tsx   # Shows model load/unload/ready status with load/unload actions
│       │   ├── GenerationStageBadge.tsx # Real-time generation stage list (top-right)
│       │   ├── ActiveGenerationsIndicator.tsx # Bottom-right global active gen pill (queue, other users)
│       │   ├── Loader.tsx             # Animated loading spinner
│       │   └── BearAnimation.tsx      # Decorative idle animation component
│       ├── hooks/
│       │   └── useGenerationStatus.ts # Hook returning human-readable generation step text
│       └── lib/
│           ├── api.ts                 # Frontend API client — health, generate, history, load/unload
│           ├── supabase.ts            # Supabase JS client initialization (auth + DB)
│           └── utils.ts               # Utility helpers (cn — clsx + tailwind-merge)
│
├── qwen_image_server/                 # Local AI Inference Server (:30000)
│   ├── main.py                        # FastAPI server wrapping QwenImage21Pipeline — T2I, I2I, load/unload, SSE progress
│   ├── smoke_test.py                  # Standalone VRAM/timing check for a new host
│   └── requirements.txt               # PyTorch (cu128), diffusers (git main), transformers >= 5.17, accelerate, fastapi
│
└── test/                              # Screenshots & test images
```

### Data Flow
1. **User** → Frontend (`:5151`) submits prompt (+ optional reference images)
2. **Frontend** → Backend (`:8181`) `POST /api/generate` with prompt + base64 images
3. **Backend** → Qwen-Image Server (`:30000`) `POST /v1/images/generations` or `/v1/images/edits`
4. **Qwen-Image Server** runs `QwenImage21Pipeline` inference (bf16, `device_map=balanced` or CPU offload)
5. **Backend** receives base64 image → uploads to Supabase Storage → inserts record to PostgreSQL → returns Generation to Frontend
6. **Frontend** displays image and updates history sidebar


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
