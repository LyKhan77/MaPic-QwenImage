# MaPic API Documentation

This document describes the REST API endpoints exposed by the MaPic application stack.

## Architecture Overview

MaPic consists of two FastAPI services:

| Service | Port | Description |
|---------|------|-------------|
| **MaPic Backend** | `:8181` | Orchestration layer — handles auth, history, storage, and proxies inference requests to the GLM-Image Server. |
| **GLM-Image Server** | `:30000` | Local inference engine — loads the GLM-Image model and runs T2I / I2I generation. |

The React frontend (`:5151`) communicates exclusively with the **MaPic Backend**. The backend then forwards generation requests to the **GLM-Image Server** internally.

---

## MaPic Backend API (`http://localhost:8181/api`)

### `GET /api/health`
Check the health status of the downstream GLM-Image Server.

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
- `offline` — GLM-Image Server is unreachable.

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
Used by the frontend to show a real-time progress bar while the GLM-Image model is being loaded. If the model is already loaded, it immediately returns `progress: 100`. If an error occurs, it returns `error: true`.

---

### `GET /api/load/state`
Fetch the persisted model loading state from the GLM-Image Server.

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
Used by the frontend to recover model loading progress after a page refresh. If the GLM-Image Server is unreachable, the backend returns an offline fallback state.

---

### `POST /api/load`
Manually load the GLM-Image model into GPU memory.

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
Manually unload the GLM-Image model to free GPU VRAM.

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
  "num_inference_steps": 35,
  "guidance_scale": 1.5
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
- `num_inference_steps` is configurable from `20` to `75`.
- `guidance_scale` is configurable from `1.0` to `5.0`.
- The backend accepts up to 10 queued/running/saving generation jobs globally.
- The generated image is uploaded to Supabase Storage and a database record is created.
- Returns the full `Generation` record including the public CDN URL.

**Errors:**
- `429` — Global generation queue is full.
- `502` — GLM-Image Server error or Supabase error.
- `500` — Internal server error.

---

### `GET /api/generations/status`
Fetch the current GLM-Image inference stage.

**Response:**
```json
{
  "stage": "diffusion",
  "step": 12,
  "total_steps": 35
}
```

**Description:**
Used by the frontend generation stage badge. Known stages include `idle`, `warmup`, `encoding`, `ar_sampling`, `diffusion`, and `decoding`.

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

## GLM-Image Server API (`http://localhost:30000`)

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
Load the GLM-Image pipeline into GPU memory.

**Response:**
```json
{
  "status": "ready"
}
```

**Description:**
- Loads the `zai-org/GLM-Image` model with 8-bit quantization (bitsandbytes) if available.
- Uses role-based multi-GPU placement.
- Pins sequential AR components and VAE to GPU 0.
- Shards the transformer across all available GPUs.
- Keeps VAE on GPU 0 to avoid tensor device mismatch.
- Enables VAE slicing, VAE tiling, attention slicing, Flash SDP / memory-efficient SDP, and `torch.compile` for the transformer.

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
  "size": "1024x1024",
  "response_format": "b64_json",
  "num_inference_steps": 50,
  "guidance_scale": 1.5
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
- `size` is snapped to the nearest multiple of 32 (e.g., `1024x1024` stays `1024x1024`).
- Runs with configurable `num_inference_steps` and `guidance_scale` values provided by the backend request.
- Returns a base64-encoded PNG image.
- Inference is protected by an `asyncio.Lock`, so only one request runs at a time.

---

### `POST /v1/images/edits`
Image-to-image generation (multi-reference).

**Request body:** `I2IRequest`
```json
{
  "prompt": "Make it cyberpunk style",
  "images": ["base64encoded...", "base64encoded..."],
  "size": "1024x1024",
  "response_format": "b64_json",
  "num_inference_steps": 35,
  "guidance_scale": 1.5
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
- Accepts up to 3 reference images as base64-encoded strings.
- Reference images are resized to the target `size` using Lanczos resampling.
- Runs with configurable `num_inference_steps` and `guidance_scale` values provided by the backend request.
- Useful for style transfer, identity preservation, and visual editing.

---

## Data Models

### `GenerateRequest`
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt` | `string` | Yes | Text prompt (max 2000 chars). |
| `user_id` | `UUID` | Yes | The user's UUID for auth and history tracking. |
| `images` | `list[string]` | No | Base64-encoded reference images for I2I (max 3). |
| `num_inference_steps` | `integer` | No | Diffusion step count, `20..75`, default `50`. |
| `guidance_scale` | `number` | No | Guidance scale, `1.0..5.0`, default `1.5`. |

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

### `T2IRequest`
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `prompt` | `string` | — | Text prompt for generation. |
| `size` | `string` | `"1024x1024"` | Output image dimensions (`WxH`). |
| `response_format` | `string` | `"b64_json"` | Response format (only `b64_json` supported). |
| `num_inference_steps` | `integer` | `50` | Diffusion step count. |
| `guidance_scale` | `number` | `1.5` | Guidance scale. |

### `I2IRequest`
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `prompt` | `string` | — | Text prompt for editing. |
| `images` | `list[string]` | — | Reference images (base64-encoded). |
| `size` | `string` | `"1024x1024"` | Output image dimensions. |
| `response_format` | `string` | `"b64_json"` | Response format. |
| `num_inference_steps` | `integer` | `35` | Diffusion step count. |
| `guidance_scale` | `number` | `1.5` | Guidance scale. |

---

## Error Handling

### MaPic Backend

| Status | Meaning |
|--------|---------|
| `429` | Global generation queue is full. |
| `500` | Unexpected internal server error. |
| `502` | Downstream service error (GLM-Image Server or Supabase). Check the `detail` field for specifics. |

### GLM-Image Server

| Condition | Response |
|-----------|----------|
| Model not loaded | `{"error": "Model failed to load"}` |
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
| `GLM_IMAGE_API_URL` | No | `http://localhost:30000` | URL of the GLM-Image Server. |
| `CORS_ORIGINS` | No | `http://localhost:5151,...` | Comma-separated allowed origins. |

### GLM-Image Server

No environment file is required. The server runs on port `30000` and downloads the model from HuggingFace on first run.

---

## Concurrency & Timeouts

- **Backend generation lock:** The MaPic Backend uses an `asyncio.Lock` around GLM generation calls so only **one accepted generation** is sent into inference at a time. Active jobs remain `queued` until they acquire this lock.
- **Inference lock:** The GLM-Image Server also uses an `asyncio.Lock` as a downstream guard to ensure only **one generation request** runs at a time.
- **Backend → GLM-Image timeout:** `14400` seconds (4 hours) to accommodate slow CPU-offloaded inference.
- **Backend retries:** Up to `6` retries with `10`-second delays on connection errors (useful when the server is still loading).
- **Model idle timeout:** The GLM-Image Server auto-unloads the model after `3600` seconds (1 hour) of inactivity to free VRAM.
