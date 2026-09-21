# MaPic API Documentation

This document describes the REST API endpoints exposed by the MaPic application stack.

## Architecture Overview

MaPic consists of two FastAPI services:

| Service | Port | Description |
|---------|------|-------------|
| **MaPic Backend** | `:8181` | Orchestration layer — handles auth, history, storage, and proxies inference requests to the Qwen-Image Server. |
| **Qwen-Image Server** | `:30000` | Local inference engine — loads the Qwen-Image 2.1 model and runs T2I / I2I generation. |

The React frontend (`:5151`) communicates exclusively with the **MaPic Backend**. The backend then forwards generation requests to the **Qwen-Image Server** internally.

---

## MaPic Backend API (`http://localhost:8181/api`)

### `GET /api/health`
Check the health status of the downstream Qwen-Image Server.

**Response:**
```json
{
  "status": "ready" | "loading" | "unloaded" | "offline"
}
```

**Description:**
- `ready` — Model is loaded and ready for inference.
- `loading` — Model is currently being loaded into GPU memory.
- `unloaded` — Model is not loaded (VRAM freed).
- `offline` — Qwen-Image Server is unreachable.

---

### `GET /api/load/stream`
Stream model loading progress via Server-Sent Events (SSE).

**Response:** `text/event-stream`

**Event format:**
```json
data: {"progress": 20, "message": "Loading pipeline weights..."}

data: {"progress": 100, "message": "Ready."}
```

**Description:**
Used by the frontend to show a real-time progress bar while the Qwen-Image 2.1 model is being loaded. If the model is already loaded, it immediately returns `progress: 100`. If an error occurs, it returns `error: true`.

---

### `GET /api/load/state`
Fetch the persisted model loading state from the Qwen-Image Server.

**Response:**
```json
{
  "status": "ready",
  "segment_index": 3,
  "segment_progress": 1.0,
  "progress": 100,
  "message": "Ready."
}
```

**Description:**
Used by the frontend to recover model loading progress after a page refresh. If the Qwen-Image Server is unreachable, the backend returns an offline fallback state.

---

### `POST /api/load`
Manually load the Qwen-Image 2.1 model into GPU memory.

**Response:**
```json
{
  "status": "ready"
}
```

**Description:**
Blocks until the model is fully loaded. Useful for pre-warming the server before generation requests. If the model is already loaded, it returns immediately.

---

### `POST /api/unload`
Manually unload the Qwen-Image 2.1 model to free GPU VRAM.

**Response:**
```json
{
  "status": "unloaded"
}
```

**Description:**
Frees all GPU memory used by the model. The model can be reloaded later manually or automatically when a generation request arrives.

---

### `POST /api/generate`
Generate an image from a text prompt (T2I) or from a prompt + reference images (I2I).

**Request body:** `GenerateRequest`
```json
{
  "prompt": "A futuristic cityscape at sunset",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "images": ["base64encodedstring..."],
  "negative_prompt": "blurry, low quality",
  "true_cfg_scale": 1.0,
  "num_inference_steps": 40,
  "resolution": 2048
}
```

**Response:** `Generation`
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440001",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "prompt": "A futuristic cityscape at sunset",
  "image_path": "550e8400-e29b-41d4-a716-446655440000/abc123.png",
  "public_url": "https://...supabase.co/storage/v1/object/public/generated_images/...",
  "created_at": "2025-01-15T10:30:00Z"
}
```

**Description:**
- If `images` is omitted or empty, performs **text-to-image (T2I)** generation.
- If `images` is provided (base64-encoded PNG/JPEG strings), performs **image-to-image (I2I)** generation using the reference images.
- `num_inference_steps` is configurable from `20` to `75` (default `40`).
- `resolution` accepts `1024` or `2048` (native 2K).
- `true_cfg_scale` accepts `1.0` to `3.0`. Qwen-Image 2.1 is sampled without guidance by default, so CFG only activates when `true_cfg_scale` is above `1.0` **and** `negative_prompt` is set — that roughly doubles the time per denoising step.
- At most 10 reference images are accepted per request.
- The backend accepts up to 10 queued/running/saving generation jobs globally.
- The generated image is uploaded to Supabase Storage and a database record is created.
- Returns the full `Generation` record including the public CDN URL.

**Errors:**
- `429` — Global generation queue is full.
- `502` — Qwen-Image Server error or Supabase error.
- `500` — Internal server error.

---

### `GET /api/generations/status`
Fetch the current Qwen-Image inference stage.

**Response:**
```json
{
  "stage": "diffusion",
  "step": 12,
  "total_steps": 35
}
```

**Description:**
Used by the frontend generation stage badge. Known stages include `idle`, `warmup`, `encoding`, `diffusion`, and `decoding`.

---

### `GET /api/generations/active`
Fetch all globally active generation jobs tracked by the backend.

**Response:** `list[ActiveGeneration]`
```json
[
  {
    "id": "active-job-id",
    "user_id": "550e8400-e29b-41d4-a716-446655440000",
    "prompt": "A futuristic cityscape at sunset",
    "elapsed_seconds": 42,
    "status": "running",
    "num_inference_steps": 35,
    "num_ref_images": 2
  }
]
```

**Description:**
Returns in-memory queued, running, and saving jobs for all users. Frontend uses this to show the bottom-right active generations indicator and to recover the current user's active generation view after refresh.

---

### `GET /api/history/{user_id}`
Fetch the generation history for a specific user.

**Path params:**
- `user_id` (UUID) — The user's UUID.

**Response:** `list[Generation]`
```json
[
  {
    "id": "...",
    "user_id": "...",
    "prompt": "...",
    "image_path": "...",
    "public_url": "...",
    "created_at": "..."
  }
]
```

**Description:**
Returns all generations for the user, sorted by `created_at` descending (newest first).

**Errors:**
- `502` — Supabase query error.
- `500` — Internal server error.

---

### `DELETE /api/history/{id}`
Delete a generation record and its associated image from storage.

**Path params:**
- `id` (UUID) — The generation record ID.

**Response:**
```json
{
  "ok": true
}
```

**Description:**
1. Looks up the generation record to find the `image_path`.
2. Deletes the image file from Supabase Storage.
3. Deletes the database record from the `generations` table.

**Errors:**
- `502` — Supabase error.
- `500` — Internal server error.

---

## Qwen-Image Server API (`http://localhost:30000`)

> **Note:** These endpoints are consumed internally by the MaPic Backend. Frontend clients should not call them directly.

### `GET /health`
Check the inference server's model status.

**Response:**
```json
{
  "status": "ready" | "loading" | "unloaded"
}
```

---

### `GET /v1/system/load/stream`
Stream model loading progress (SSE).

**Response:** `text/event-stream`

**Event format:**
```json
data: {"progress": 10, "message": "Initializing loading..."}
```

**Description:**
Starts model loading in a background thread and streams progress updates. Used by the backend's `/api/load/stream` endpoint.

---

### `GET /v1/system/load/state`
Fetch current model load state.

**Response:**
```json
{
  "status": "ready",
  "segment_index": 3,
  "segment_progress": 1.0,
  "progress": 100,
  "message": "Ready."
}
```

**Description:**
Used by the backend's `/api/load/state` proxy endpoint so the frontend can recover loading progress after refresh.

---

### `POST /v1/system/load`
Load the Qwen-Image 2.1 pipeline into GPU memory.

**Response:**
```json
{
  "status": "ready"
}
```

**Description:**
- Loads `Qwen/Qwen-Image-2.1` in bf16 (7B single-stream DiT + Qwen3-VL 8B encoder + 64-channel RGBA VAE).
- Shards the pipeline across GPUs with `device_map="balanced"`, bounded by `QWEN_MAX_MEMORY`.
- With `QWEN_CPU_OFFLOAD=1` the pipeline loads without sharding and streams modules on demand instead (slower, far less VRAM).
- Enables VAE slicing, VAE tiling, Flash SDP, and memory-efficient SDP.
- Requests above `QWEN_MAX_RESOLUTION` are rejected so a low-VRAM host cannot OOM.

---

### `POST /v1/system/unload`
Unload the model and free all GPU memory.

**Response:**
```json
{
  "status": "unloaded"
}
```

---

### `POST /v1/images/generations`
Text-to-image generation.

**Request body:** `T2IRequest`
```json
{
  "prompt": "A serene mountain lake at dawn",
  "negative_prompt": "blurry, low quality",
  "true_cfg_scale": 1.0,
  "resolution": 2048,
  "size": "2048x2048",
  "response_format": "b64_json",
  "num_inference_steps": 40
}
```

**Response:**
```json
{
  "data": [
    {
      "b64_json": "iVBORw0KGgoAAAANSUhEUgAA..."
    }
  ]
}
```

**Description:**
- `resolution` sets the output size (`1024` or `2048`). An explicit `size` (`WxH`) overrides it and is snapped down to a multiple of 32.
- `true_cfg_scale` above `1.0` only takes effect together with `negative_prompt`.
- Returns a base64-encoded PNG image (RGBA when the model produces transparency).
- Inference is protected by an `asyncio.Lock`, so only one request runs at a time.

---

### `POST /v1/images/edits`
Image-to-image generation (multi-reference).

**Request body:** `I2IRequest`
```json
{
  "prompt": "Make it cyberpunk style",
  "images": ["base64encoded...", "base64encoded..."],
  "negative_prompt": "blurry, low quality",
  "true_cfg_scale": 1.0,
  "resolution": 2048,
  "response_format": "b64_json",
  "num_inference_steps": 40
}
```

**Response:**
```json
{
  "data": [
    {
      "b64_json": "iVBORw0KGgoAAAANSUhEUgAA..."
    }
  ]
}
```

**Description:**
- Accepts up to 10 reference images as base64-encoded strings.
- Reference images are passed through untouched: the pipeline resizes each one into its own aspect-ratio bucket before encoding.
- `resolution` (or an explicit `size`) sets the output size; when neither is given, the aspect ratio follows the last reference image.
- `true_cfg_scale` above `1.0` only takes effect together with `negative_prompt`.
- Useful for style transfer, identity preservation, visual editing, and multi-subject composition.

---

## Data Models

### `GenerateRequest`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt` | `string` | Yes | Text prompt (max 2000 chars). |
| `user_id` | `UUID` | Yes | The user's UUID for auth and history tracking. |
| `images` | `list[string]` | No | Base64-encoded reference images for I2I (max 10). |
| `negative_prompt` | `string` | No | Text to steer away from; required for CFG to activate. |
| `true_cfg_scale` | `number` | No | CFG scale, `1.0..3.0`, default `1.0` (guidance off). |
| `num_inference_steps` | `integer` | No | Diffusion step count, `20..75`, default `40`. |
| `resolution` | `integer` | No | `1024` or `2048`, default `2048`. |

### `Generation`
| Field | Type | Description |
|-------|------|-------------|
| `id` | `UUID` | Unique record ID. |
| `user_id` | `UUID` | Owner of the generation. |
| `prompt` | `string` | The prompt used. |
| `image_path` | `string` | Internal Supabase Storage path. |
| `public_url` | `string` | Publicly accessible CDN URL. |
| `created_at` | `datetime` | ISO 8601 timestamp. |

### `ActiveGeneration`
| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | In-memory active generation ID. |
| `user_id` | `string` | Owner user ID. |
| `prompt` | `string` | Prompt being generated. |
| `elapsed_seconds` | `integer` | Seconds since the job started running. Queued jobs return `0`. |
| `status` | `string` | `queued`, `running`, or `saving`. |
| `num_inference_steps` | `integer` | Requested step count. |
| `num_ref_images` | `integer` | Number of reference images attached to the job. |
| `resolution` | `integer` | Requested output resolution (`1024` or `2048`). |
| `cfg_enabled` | `boolean` | `true` when classifier-free guidance is active for the job. |

### `T2IRequest`
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `prompt` | `string` | — | Text prompt for generation. |
| `negative_prompt` | `string` | `null` | Negative prompt; required for CFG. |
| `true_cfg_scale` | `number` | `1.0` | CFG scale; `1.0` disables guidance. |
| `resolution` | `integer` | `2048` | Output size when `size` is not given. |
| `size` | `string` | `null` | Explicit `WxH`; snapped down to a multiple of 32. |
| `response_format` | `string` | `"b64_json"` | Response format (only `b64_json` supported). |
| `num_inference_steps` | `integer` | `40` | Diffusion step count. |

### `I2IRequest`
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `prompt` | `string` | — | Text prompt for editing. |
| `images` | `list[string]` | — | Reference images (base64-encoded, max 10). |
| `negative_prompt` | `string` | `null` | Negative prompt; required for CFG. |
| `true_cfg_scale` | `number` | `1.0` | CFG scale; `1.0` disables guidance. |
| `resolution` | `integer` | `2048` | Output size when `size` is not given. |
| `size` | `string` | `null` | Explicit `WxH`; when omitted the aspect ratio follows the last reference image. |
| `response_format` | `string` | `"b64_json"` | Response format. |
| `num_inference_steps` | `integer` | `40` | Diffusion step count. |

---

## Error Handling

### MaPic Backend

| Status | Meaning |
|--------|---------|
| `429` | Global generation queue is full. |
| `500` | Unexpected internal server error. |
| `502` | Downstream service error (Qwen-Image Server or Supabase). Check the `detail` field for specifics. |

### Qwen-Image Server

| Condition | Response |
|-----------|----------|
| Model not loaded | `{"error": "Model failed to load"}` |
| Resolution above `QWEN_MAX_RESOLUTION` | `{"error": "Resolution ... exceeds this server's limit of ..."}` |
| More than 10 reference images | `{"error": "Qwen-Image 2.1 supports at most 10 reference images"}` |
| Loading in progress | `{"status": "loading"}` on `/health` |

---

## CORS

The MaPic Backend is configured with CORS to accept requests from the following origins (configurable via `CORS_ORIGINS` env var):

- `http://localhost:5151`
- `http://localhost:5152`
- `http://127.0.0.1:5151`
- `http://127.0.0.1:5152`
- `https://mapic-glm.vercel.app`

---

## Database And Storage Schema

See [`database-schema.md`](./database-schema.md) for the Supabase Auth, Postgres, RLS, and Storage schema used by these API endpoints.

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SUPABASE_URL` | Yes | — | Supabase project URL. |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | — | Supabase service role key (admin). |
| `QWEN_IMAGE_API_URL` | No | `http://localhost:30000` | URL of the Qwen-Image Server. |
| `QWEN_DEFAULT_RESOLUTION` | No | `2048` | Default output resolution (`1024` or `2048`). |
| `CORS_ORIGINS` | No | `http://localhost:5151,...` | Comma-separated allowed origins. |

### Qwen-Image Server

The server reads its configuration from the environment instead of an env file:

| Variable | Default | Description |
|----------|---------|-------------|
| `QWEN_MAX_MEMORY` | `{"cpu": "8GiB"}` | Per-device memory ceiling for `device_map="balanced"`. |
| `QWEN_CPU_OFFLOAD` | `0` | `1` streams modules on demand instead of sharding (slower, less VRAM). |
| `QWEN_MAX_RESOLUTION` | `2048` | Requests above this are rejected with an error. |
| `HF_HOME` | library default | Where the ~47 GB of weights are cached. |

The server runs on port `30000` and downloads the model from HuggingFace on first run.

---

## Concurrency & Timeouts

- **Backend generation lock:** The MaPic Backend uses an `asyncio.Lock` around Qwen generation calls so only **one accepted generation** is sent into inference at a time. Active jobs remain `queued` until they acquire this lock.
- **Inference lock:** The Qwen-Image Server also uses an `asyncio.Lock` as a downstream guard to ensure only **one generation request** runs at a time.
- **Backend → Qwen-Image timeout:** `3600` seconds (1 hour). Enabling CFG roughly doubles each denoising step, so a 2K job with guidance takes the longest.
- **Backend retries:** Up to `6` retries with `10`-second delays on connection errors (useful when the server is still loading).
- **Model idle timeout:** The Qwen-Image Server auto-unloads the model after `3600` seconds (1 hour) of inactivity to free VRAM.
