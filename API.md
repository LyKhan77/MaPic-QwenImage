# MaPic API Documentation

This document describes the REST API endpoints exposed by the MaPic application stack.

## Architecture Overview

MaPic consists of two FastAPI services:

| Service | Port | Description |
|---------|------|-------------|
| **Frontend** | `:5151` | React SPA yang disajikan nginx di dalam container. |
| **MaPic Backend** | `:8281` | Orchestration layer — handles auth, history, storage, and proxies inference requests to the Qwen-Image Server. |
| **Qwen-Image Server (facade)** | `:30000` | Penerjemah — menyusun graph ComfyUI dari request, meneruskan progres. Tidak diekspos ke host. |
| **ComfyUI** | `127.0.0.1:8188` | Engine inference sebenarnya: menjalankan Qwen-Image 2.1 GGUF di GPU. Hanya localhost. |

The React frontend (`:5151`) communicates exclusively with the **MaPic Backend**. The backend then forwards generation requests to the facade, which drives ComfyUI — semuanya di network internal Docker.

---

## MaPic Backend API (`http://localhost:8281/api`)

### Authentication

Endpoint pengguna (semua kecuali `GET /api/health` dan route service) memerlukan header:

```
Authorization: Bearer <access_token Supabase>
```

Backend memverifikasi tanda tangan token lewat JWKS project (kunci asimetris ES256/RS256) dan memakai claim `sub` sebagai identitas user. `user_id` yang dikirim klien di body atau URL **diabaikan/diverifikasi**, sehingga tidak ada lagi cara memanggil API sebagai user lain hanya dengan menebak UUID.

Route service (`POST /api/service/generate`) memakai kredensial mesin terpisah dari environment backend — lihat [Service API](#post-apiservicegenerate). JWT pengguna **tidak** berlaku di route service, dan token service **tidak** berlaku di endpoint pengguna (ditolak `401` sebelum menyentuh JWKS).

| Kode | Arti |
|---|---|
| `401` | Header `Authorization` tidak ada, atau token tidak valid/kedaluwarsa |
| `403` | Token valid, tetapi mencoba membaca riwayat milik user lain |

Frontend mengambil token dari sesi Supabase aktif (`supabase.auth.getSession()`) dan menempelkannya ke setiap request di `frontend/src/lib/api.ts`.

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
  "images": ["base64encodedstring..."],
  "negative_prompt": "blurry, low quality",
  "true_cfg_scale": 1.0,
  "num_inference_steps": 40,
  "resolution": 1024
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
- `resolution` accepts `1024` atau `2048` di skema; host ini memblokir 2048 karena VRAM 16 GB — facade menolaknya dengan HTTP 400 sebelum inference dan backend meneruskannya sebagai `502` untuk endpoint pengguna (bukan OOM).
- `true_cfg_scale` accepts `1.0` to `3.0`. Qwen-Image 2.1 is sampled without guidance by default, so CFG only activates when `true_cfg_scale` is above `1.0` **and** `negative_prompt` is set — that roughly doubles the time per denoising step.
- At most 10 reference images are accepted per request.
- The backend accepts up to 10 queued/running/saving generation jobs globally.
- Pemilik hasil adalah `sub` dari token, bukan field di body — klien tidak bisa menitipkan pekerjaan atas nama user lain.
- The generated image is uploaded to Supabase Storage and a database record is created.
- Returns the full `Generation` record including the public CDN URL.

**Errors:**
- `429` — Global generation queue is full.
- `502` — Qwen-Image Server error or Supabase error.
- `500` — Internal server error.

---

### `POST /api/service/generate`
Generate mesin-ke-mesin untuk backend lokal **Inkspire**: satu endpoint untuk text-to-image dan image-to-image, tanpa login Supabase. Hasil dikembalikan langsung sebagai PNG base64 dan **tidak** disimpan di MaPic.

**Autentikasi:** `Authorization: Bearer <MAPIC_SERVICE_TOKEN>`. Token adalah kredensial mesin dari environment backend — bukan JWT Supabase dan bukan service-role key Supabase. Client yang benar adalah backend lokal Inkspire (server-ke-server) lewat LAN; jangan memanggilnya dari JavaScript browser. JWT pengguna tidak diterima di route ini, dan token service tidak berlaku di endpoint pengguna.

**Request body:** `ServiceGenerateRequest` — field sama dengan `GenerateRequest`, dengan satu tambahan aturan: `prompt` wajib tidak kosong setelah trim.

Contoh T2I:

```json
{
  "prompt": "Minimal green ink illustration of a creative workspace",
  "negative_prompt": "",
  "true_cfg_scale": 1.0,
  "num_inference_steps": 40,
  "resolution": 1024
}
```

Contoh I2I (maksimal 10 referensi):

```json
{
  "prompt": "Turn this sketch into a clean product illustration",
  "images": ["<base64 PNG/JPEG tanpa prefiks data URL>"],
  "true_cfg_scale": 1.0,
  "num_inference_steps": 40,
  "resolution": 1024
}
```

**Response `200`** (dikirim setelah generation selesai — endpoint blocking, sama untuk T2I dan I2I):

```json
{
  "data": [
    {
      "b64_json": "<PNG base64>"
    }
  ]
}
```

**Batas payload (semua dicek sebelum inference, sebelum slot antrean diambil):**

| Batas | Nilai | Pelanggaran |
|---|---|---|
| Body request mentah | 32 MiB | `413` |
| String base64 per gambar | 2.800.000 karakter | `413` |
| Byte hasil decode per gambar | 2 MiB | `413` |
| Sisi gambar | 2048 px | `422` |
| Piksel gambar | 4.194.304 | `422` |
| Jumlah gambar | 10 | `422` |
| `num_inference_steps` | 20–75, default 40 | `422` |
| `true_cfg_scale` | 1.0–3.0, default 1.0 | `422` |
| `resolution` | ≤ `QWEN_MAX_RESOLUTION` (1024 di host ini) | `422` |

Klien (Inkspire) harus mengecilkan gambar sebelum mengirim; jumlah gambar saja tidak membatasi konsumsi memori server.

**Errors:**
- `401` — Header hilang, skema bukan `Bearer`, atau token salah.
- `413` — Body request atau gambar referensi melebihi batas.
- `422` — Input tidak valid (prompt kosong/terlalu panjang, steps/CFG/resolusi di luar rentang, lebih dari 10 gambar, base64 rusak, format bukan PNG/JPEG, dimensi terlalu besar).
- `429` — Antrean generasi gabungan (pengguna + service) penuh.
- `502` — Downstream gagal atau memberi hasil tidak valid.
- `503` — Service API dinonaktifkan (`MAPIC_SERVICE_TOKEN` kosong/tidak diset).
- `504` — Downstream generation timeout.
- `500` — Internal server error.

Pesan `502`/`504` sengaja umum; detail lengkap hanya ada di log server. Body `422` mengikuti bentuk validasi FastAPI (`type`/`loc`/`msg`, `loc` diawali `body`) tanpa menggemakan nilai input yang dikirim. Tidak ada retry otomatis setelah timeout.

**Sifat jalur service:**
- **Stateless.** Tidak ada verifikasi Supabase Auth/JWKS, tidak ada `user_id`, tidak ada record history, upload Storage, atau `public_url`. Prompt, gambar referensi, dan hasil tidak disimpan permanen di MaPic. Metadata antrean sementara (tanpa prompt/gambar/identitas) dihapus begitu job selesai/gagal.
- **Antrean dan lock bersama.** Job service memakai mekanisme admission dan `_generation_lock` yang sama dengan endpoint pengguna; batas 10 pekerjaan berlaku untuk gabungan kedua jalur. Job service tidak muncul di `GET /api/generations/active`.
- **Blocking, tanpa progress per-job atau cancel.** `GET /api/health` tetap satu-satunya penanda kesiapan model; status di `GET /api/generations/status` bersifat global, bukan progress request tertentu. Client yang disconnect tidak membatalkan job GPU — facade tidak mendukung cancellation.
- **Tanpa Supabase di jalur request.** Aplikasi MaPic secara keseluruhan tetap membutuhkan konfigurasi Supabase saat start (dan membuat klien Supabase saat import); yang dijamin bebas panggilan Supabase adalah jalur request service generation.

**Contoh aman** (nilai diambil dari environment lokal, bukan ditulis ke source atau config yang di-commit):

```sh
# MAPIC_BASE_URL dan MAPIC_SERVICE_TOKEN diisi di environment lokal,
# bukan ditulis ke source code atau committed config.
curl --fail-with-body --silent --show-error \
  --request POST "$MAPIC_BASE_URL/api/service/generate" \
  --header "Authorization: Bearer $MAPIC_SERVICE_TOKEN" \
  --header 'Content-Type: application/json' \
  --data '{"prompt":"Minimal green ink illustration","resolution":1024,"num_inference_steps":40}' \
  --output generation.json
```

**Mengaktifkan/menonaktifkan.** Isi atau kosongkan `MAPIC_SERVICE_TOKEN` di `backend/.env`, lalu `docker compose restart backend`. Token kosong = route service `503` (fail closed); endpoint pengguna tidak terpengaruh. Cara rotasi dan rollback ada di `deploy/docker/README.md`.

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
Returns all generations for the user, sorted by `created_at` descending (newest first). `user_id` harus sama dengan `sub` di token; permintaan untuk user lain ditolak sebelum menyentuh Supabase.

**Errors:**
- `401` — Token tidak ada/tidak valid.
- `403` — `user_id` berbeda dari pemilik token.
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
1. Looks up the generation record **milik user pemilik token** — baris milik user lain tidak terlihat sama sekali.
2. Deletes the image file from Supabase Storage.
3. Deletes the database record from the `generations` table.

**Errors:**
- `401` — Token tidak ada/tidak valid.
- `404` — Record tidak ditemukan, atau bukan milik user pemilik token.
- `502` — Supabase error.
- `500` — Internal server error.

---

### `POST /api/remove-background`
Hapus latar satu gambar (PNG/JPEG) dan simpan hasil PNG transparan sebagai record riwayat baru. Jalur CPU terpisah dari Qwen; model Qwen yang `unloaded` tidak menghalangi endpoint ini.

> **INTERNAL USE ONLY.** Endpoint ini memakai bobot `isnet-general-use.onnx` yang tidak memiliki pernyataan lisensi (repo DIS ber-Apache-2.0 hanya untuk kode/metrik; dataset DIS5K non-komersial; issue [#150](https://github.com/xuebinqin/DIS/issues/150) belum terjawab). Jangan dipakai untuk pekerjaan komersial atau didistribusikan sampai lisensi diselesaikan atau model diganti.

**Request body:**
```json
{
  "image": "base64encodedstring",
  "source_label": "cocacola.jpg"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `image` | `string` | Yes | Base64 PNG/JPEG tanpa prefiks data-URL. Maksimal 2 MiB setelah decode, sisi maksimal 2048 px. |
| `source_label` | `string` | No | Label tampilan untuk sumber cutout (mis. nama berkas), maksimal 200 karakter di level skema. **Display only**: server menyaringnya (karakter kontrol → spasi, runtun spasi → satu spasi, dipotong 80 karakter) lalu menyimpannya sebagai `Remove background — <label>`. Label ini tidak pernah dipakai untuk path Storage, header, query, atau nama berkas, dan tidak boleh dipercaya sebagai data. Tanpa label yang bisa dibaca, prompt tersimpan tetap persis `Remove background` (baris lama di riwayat juga tetap berbunyi begitu). |

**Response:** `Generation` dengan `prompt` = `Remove background` atau `Remove background — <label>`.

**Errors:**
- `401` — Token tidak ada/tidak valid.
- `413` — Payload gambar terlalu besar.
- `422` — Base64/format/dimensi tidak valid.
- `429` — Worker cutout sedang sibuk.
- `503` — Model cutout tidak tersedia.
- `502` — Inferensi atau Supabase gagal.

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
Starts model loading in a background thread and streams progress updates. Endpoint internal facade — backend tidak lagi memakainya (progress model dibaca lewat `/v1/system/load/state`), dan tidak diteruskan ke klien.

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
- Menjalankan *warmup* satu step di 256×256. ComfyUI memuat model saat job pertama dieksekusi, jadi "load" berarti memicu pemuatan itu lebih dulu supaya request pengguna tidak menanggung waktunya.
- Memuat model Qwen-Image 2.1 GGUF **Q8_0** (7,07 GiB) + text encoder int8 (8,71 GiB) + VAE bf16 (0,63 GiB) dengan *dynamic VRAM loading* — ketiganya dimuat bergantian, bukan bersamaan.
- Container ComfyUI dipin ke satu GPU lewat `NVIDIA_VISIBLE_DEVICES`.
- Permintaan di atas `QWEN_MAX_RESOLUTION` ditolak dengan HTTP 400 sehingga host ber-VRAM kecil tidak pernah OOM.

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
  "resolution": 1024,
  "size": "1024x1024",
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
- `resolution` sets the output size (`1024` di host ini). An explicit `size` (`WxH`) overrides it and is snapped down to a multiple of 32; nilai di atas `QWEN_MAX_RESOLUTION` ditolak.
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
  "resolution": 1024,
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
| `images` | `list[string]` | No | Base64-encoded reference images for I2I (max 10). |
| `negative_prompt` | `string` | No | Text to steer away from; required for CFG to activate. |
| `true_cfg_scale` | `number` | No | CFG scale, `1.0..3.0`, default `1.0` (guidance off). |
| `num_inference_steps` | `integer` | No | Diffusion step count, `20..75`, default `40`. |
| `resolution` | `integer` | No | `1024` (host ini menolak `2048`), default `1024`. |

### `ServiceGenerateRequest`
Field sama dengan `GenerateRequest` (termasuk `images` maksimal 10), dengan tambahan aturan: `prompt` wajib dan tidak kosong setelah trim.

### `ServiceImageResponse`
| Field | Type | Description |
|-------|------|-------------|
| `data` | `list[ServiceImage]` | Selalu berisi satu elemen untuk endpoint ini. |
| `data[].b64_json` | `string` | PNG hasil generation, base64 tanpa prefiks data URL. |

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
| `resolution` | `integer` | Requested output resolution (`1024` di host ini). |
| `cfg_enabled` | `boolean` | `true` when classifier-free guidance is active for the job. |

### `T2IRequest`
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `prompt` | `string` | — | Text prompt for generation. |
| `negative_prompt` | `string` | `null` | Negative prompt; required for CFG. |
| `true_cfg_scale` | `number` | `1.0` | CFG scale; `1.0` disables guidance. |
| `resolution` | `integer` | `1024` | Output size when `size` is not given. |
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
| `resolution` | `integer` | `1024` | Output size when `size` is not given. |
| `size` | `string` | `null` | Explicit `WxH`; when omitted the aspect ratio follows the last reference image. |
| `response_format` | `string` | `"b64_json"` | Response format. |
| `num_inference_steps` | `integer` | `40` | Diffusion step count. |

---

## Error Handling

### MaPic Backend

| Status | Meaning |
|--------|---------|
| `401` | Token tidak ada/tidak valid — JWT pengguna di endpoint pengguna, atau token service di route service. |
| `403` | JWT valid tetapi mencoba membaca riwayat milik user lain. |
| `413` | Payload gambar/body melebihi batas (Remove Background dan service generate). |
| `422` | Input tidak valid (skema, base64, format, atau dimensi gambar). |
| `429` | Antrean generasi gabungan (pengguna + service) penuh. |
| `500` | Unexpected internal server error. |
| `502` | Downstream service error (Qwen-Image Server atau Supabase). Di endpoint pengguna `detail` memuat pesan spesifik; di endpoint service pesan sengaja umum dan detailnya hanya di log server. |
| `503` | Layanan tidak tersedia — model cutout hilang, atau service API dinonaktifkan (token kosong). |
| `504` | Downstream generation timeout (endpoint service). |

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

- `http://192.168.2.142:5151` (frontend di LAN kantor — origin yang dipakai sehari-hari)
- `http://localhost:5151`, `http://localhost:5152`, `http://127.0.0.1:5151`, `http://127.0.0.1:5152` (pengembangan lokal)

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
| `QWEN_DEFAULT_RESOLUTION` | No | `1024` | Default output resolution. |
| `QWEN_MAX_RESOLUTION` | No | mengikuti `QWEN_DEFAULT_RESOLUTION` | Batas resolusi endpoint service; samakan dengan `QWEN_MAX_RESOLUTION` layanan facade. |
| `MAPIC_SERVICE_TOKEN` | No | — (kosong) | Token mesin endpoint service. Kosong/tidak diset = route service `503` (fail closed). Nilai asli hanya di `backend/.env` server. |
| `CORS_ORIGINS` | No | `http://localhost:5151,...` | Comma-separated allowed origins. |

### Qwen-Image Server

The server reads its configuration from the environment instead of an env file:

| Variable | Default | Description |
|----------|---------|-------------|
| `COMFY_BASE_URL` | `http://comfyui:8188` | Alamat ComfyUI di network internal Docker. |
| `QWEN_GGUF_NAME` | `qwen-image-2.1-Q8_0.gguf` | Nama file model di dalam folder yang di-mount ke ComfyUI. Ganti di sini bila memakai kuantisasi lain. |
| `QWEN_CLIP_NAME` | `qwen3vl_8b_int8_convrot.safetensors` | Text encoder. |
| `QWEN_VAE_NAME` | `qwen_image_2.1_vae_bf16.safetensors` | VAE. |
| `QWEN_MAX_RESOLUTION` | `1024` | Requests above this are rejected with HTTP 400. |

The facade listens on port `30000` **hanya di network internal Docker** — tidak ada port host yang dipublikasikan. Model tidak diunduh saat runtime: ia di-mount read-only ke container ComfyUI dari folder di host (struktur foldernya di `deploy/docker/README.md`).

---

## Concurrency & Timeouts

- **Backend generation lock:** The MaPic Backend uses an `asyncio.Lock` around Qwen generation calls so only **one accepted generation** is sent into inference at a time. Active jobs remain `queued` until they acquire this lock. Endpoint pengguna dan endpoint service memakai lock yang sama.
- **Admission gabungan:** batas 10 pekerjaan dihitung dari gabungan jalur pengguna dan service. Slot dilepas pada sukses, exception, timeout, maupun pembatalan request. Penghitung antrean hanya berlaku per proses backend (satu container, satu worker uvicorn) — jangan menaikkan jumlah worker tanpa memindahkan penghitung keluar memori.
- **Job service dan daftar aktif:** job service tidak muncul di `GET /api/generations/active` dan metadatanya tidak memuat prompt, gambar, atau identitas pengguna.
- **Inference lock:** The Qwen-Image Server also uses an `asyncio.Lock` as a downstream guard to ensure only **one generation request** runs at a time.
- **Backend → Qwen-Image timeout:** `3600` seconds (1 hour). Enabling CFG roughly doubles each denoising step, so a job with guidance takes the longest.
- **Timeout di endpoint service:** dipetakan ke HTTP `504` dan **tidak** di-retry otomatis — job mungkin sudah diterima facade, jadi percobaan ulang berisiko menggandakan generation.
- **Backend retries:** Up to `6` retries with `10`-second delays on connection errors only (termasuk connect timeout — koneksi belum pernah terbentuk, jadi aman diulang; berguna saat server masih memuat model). Kegagalan ambigu setelah request terkirim tidak pernah di-retry.
- **Model idle timeout:** The Qwen-Image Server auto-unloads the model after `3600` seconds (1 hour) of inactivity to free VRAM.
- **Disconnect klien:** endpoint generate bersifat blocking. Facade tidak mendukung cancellation, jadi client yang putus di tengah generation **tidak** menghentikan job GPU; slot backend dilepas saat handler selesai/gagal/dibatalkan, dan facade tetap menahan inference lock-nya sendiri sehingga tidak pernah ada dua inference bersamaan.
- **Reverse proxy:** tidak ada proxy yang memotong request lebih awal pada deployment saat ini. Kalau menambahkan reverse proxy (mis. HTTPS untuk LAN), atur timeout-nya lebih panjang dari 3600 detik.
