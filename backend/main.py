import asyncio
import base64
import binascii
import logging
import time
from io import BytesIO
from uuid import UUID, uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import ValidationError
import uvicorn.logging

try:
    from backend.auth import require_service_token, require_user
    from backend.config import CORS_ORIGINS, QWEN_IMAGE_API_URL, QWEN_MAX_RESOLUTION
    from backend.schemas import ActiveGeneration, GenerateRequest, Generation, RemoveBackgroundRequest, ServiceGenerateRequest, ServiceImageResponse
    from backend.services import remove_background_service
    from backend.services.qwen_image_service import QwenImageError, QwenImageTimeoutError, generate_image_bytes, get_generation_status, get_health_status, get_load_state, load_model, unload_model
    from backend.services.supabase_service import (
        GenerationNotFound,
        SupabaseError,
        delete_generation,
        delete_stored_image,
        fetch_history,
        insert_generation,
        upload_image,
    )
except ModuleNotFoundError:
    from auth import require_service_token, require_user
    from config import CORS_ORIGINS, QWEN_IMAGE_API_URL, QWEN_MAX_RESOLUTION
    from schemas import ActiveGeneration, GenerateRequest, Generation, RemoveBackgroundRequest, ServiceGenerateRequest, ServiceImageResponse
    from services import remove_background_service
    from services.qwen_image_service import QwenImageError, QwenImageTimeoutError, generate_image_bytes, get_generation_status, get_health_status, get_load_state, load_model, unload_model
    from services.supabase_service import (
        GenerationNotFound,
        SupabaseError,
        delete_generation,
        delete_stored_image,
        fetch_history,
        insert_generation,
        upload_image,
    )

app = FastAPI(title="Mapic API", version="1.0.0")
logger = logging.getLogger("mapic")

# Suppress access logs for successful polling GETs to reduce log noise
class _QuietPollingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        # Suppress 200 OK responses for GET requests (health checks, status polling)
        if '"GET ' in msg and '200 OK' in msg:
            return False
        return True

_logging_configured = False
if not _logging_configured:
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.addFilter(_QuietPollingFilter())
    _logging_configured = True

# In-memory tracking of active generations
MAX_GLOBAL_GENERATIONS = 10
_active_generations: dict[str, dict] = {}
_generation_lock = asyncio.Lock()

# Remove Background runs on CPU in a separate worker and never touches the Qwen
# queue, so it has its own lock. Single slot on purpose: the process can safely
# hold only one ~3 GiB ONNX session, so a second concurrent request is refused
# with 429 rather than queued. ponytail: raise the slot count only after the
# hosted RAM can hold another session.
_remove_background_lock = asyncio.Lock()

# Larger payloads than this are refused before base64 decoding (~2 MiB PNG/JPEG).
MAX_REMOVE_BACKGROUND_BASE64_CHARS = 2_800_000
MAX_REMOVE_BACKGROUND_BYTES = 2 * 1024 * 1024
MAX_REMOVE_BACKGROUND_SIDE = 2048
MAX_REMOVE_BACKGROUND_PIXELS = 4_194_304
REMOVE_BACKGROUND_PROMPT = "Remove background"
MAX_SOURCE_LABEL_CHARS = 80

# Service API (untuk backend lokal Inkspire): jalur stateless tanpa Supabase.
# Batas gambar menyamakan nilai dengan batas cutout di atas — host ini punya RAM
# terbatas, dan jumlah gambar saja tidak membatasi konsumsi memori. Klien
# (Inkspire) harus mengecilkan gambar sebelum mengirim; nilainya didokumentasikan
# di API.md.
MAX_SERVICE_REQUEST_BYTES = 32 * 1024 * 1024  # body JSON mentah, sebelum parsing
MAX_SERVICE_IMAGE_BASE64_CHARS = 2_800_000  # ~2 MiB PNG/JPEG per gambar
MAX_SERVICE_IMAGE_BYTES = 2 * 1024 * 1024
MAX_SERVICE_IMAGE_SIDE = 2048
MAX_SERVICE_IMAGE_PIXELS = 4_194_304


def _clean_source_label(raw: str | None) -> str:
    """Collapse a client-supplied label to one short, safe display line.

    Tampilan saja: label ini tidak pernah dipakai untuk path penyimpanan, header,
    query, atau nama berkas.
    """
    if not raw:
        return ""
    # Karakter kontrol bisa merusak tinggi baris di sidebar, bukan hanya \n dan \t.
    flattened = "".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in raw)
    collapsed = " ".join(flattened.split())  # str.split() juga memecah U+00A0
    return collapsed[:MAX_SOURCE_LABEL_CHARS].strip()


def _history_prompt_for_cutout(label: str) -> str:
    """Bentuk prompt riwayat cutout; tanpa label yang bisa dipakai, label lama."""
    return f"{REMOVE_BACKGROUND_PROMPT} — {label}" if label else REMOVE_BACKGROUND_PROMPT


def _can_accept_generation(active_generations: dict[str, dict]) -> bool:
    return len(active_generations) < MAX_GLOBAL_GENERATIONS


async def _read_limited_body(request: Request, max_bytes: int) -> bytes:
    """Baca body request dengan batas keras sebelum JSON diparsing.

    Header `Content-Length` saja tidak cukup (bisa absen pada body chunked), jadi
    hitungan byte dilakukan saat streaming dan pembacaan dihentikan begitu batas
    terlampaui.
    """
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise HTTPException(status_code=413, detail="Request body is too large")
    return bytes(body)


def _validate_service_images(images: list[str] | None) -> None:
    """Tolak gambar referensi yang terlalu besar/rusak sebelum inference.

    Dipanggil sebelum job masuk antrean, jadi request yang jelas salah tidak
    memakan slot. Pemeriksaan ukuran/dimensi dibaca dari header gambar lebih dulu
    (tanpa memuat piksel penuh) supaya PNG kecil berisi dimensi raksasa tidak
    sempat didekode. Satu-satunya data yang menyentuh disk/memori adalah salinan
    sementara yang dibuang lagi di akhir fungsi.
    """
    for index, encoded in enumerate(images or [], start=1):
        if len(encoded) > MAX_SERVICE_IMAGE_BASE64_CHARS:
            raise HTTPException(status_code=413, detail=f"Reference image {index} is too large")

        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Reference image {index} is not valid base64") from exc

        if len(raw) > MAX_SERVICE_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail=f"Reference image {index} is too large")

        try:
            image = Image.open(BytesIO(raw))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Reference image {index} could not be read") from exc

        with image:
            if image.format not in {"PNG", "JPEG"}:
                raise HTTPException(status_code=422, detail=f"Reference image {index} must be PNG or JPEG")
            width, height = image.size
            if (
                width <= 0
                or height <= 0
                or max(width, height) > MAX_SERVICE_IMAGE_SIDE
                or width * height > MAX_SERVICE_IMAGE_PIXELS
            ):
                raise HTTPException(
                    status_code=422,
                    detail=f"Reference image {index} dimensions {width}x{height} exceed the supported range",
                )
            try:
                image.load()
            except Exception as exc:
                raise HTTPException(status_code=422, detail=f"Reference image {index} could not be read") from exc


origins = [origin.strip() for origin in CORS_ORIGINS.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def api_health():
    status = await get_health_status()
    return {"status": status}


@app.post("/api/load")
async def api_load(_: UUID = Depends(require_user)):
    try:
        result = await load_model()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/unload")
async def api_unload(_: UUID = Depends(require_user)):
    try:
        result = await unload_model()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/load/state")
async def api_load_state(_: UUID = Depends(require_user)):
    try:
        return await get_load_state()
    except Exception as exc:
        logger.warning("Load state check failed: %s", exc)
        return {"status": "offline", "segment_index": 0, "segment_progress": 0.0, "progress": 0, "message": ""}


@app.get("/api/generations/status")
async def api_generation_status(_: UUID = Depends(require_user)):
    try:
        return await get_generation_status()
    except Exception as exc:
        logger.warning("Generation status failed: %s", exc)
        return {"stage": "idle", "step": 0, "total_steps": 0}


@app.get("/api/generations/active", response_model=list[ActiveGeneration])
async def api_active_generations(_: UUID = Depends(require_user)):
    now = time.time()
    result = []
    for gen_id, info in _active_generations.items():
        # Job service tidak punya identitas pengguna dan prompt/gambarnya tidak
        # pernah disimpan, jadi tidak pernah muncul di daftar milik pengguna.
        if info.get("kind") == "service":
            continue
        result.append(ActiveGeneration(
            id=gen_id,
            user_id=str(info["user_id"]),
            prompt=info["prompt"],
            elapsed_seconds=int(now - info["started_at"]) if info.get("started_at") else 0,
            status=info.get("status", "running"),
            num_inference_steps=info.get("num_inference_steps", 40),
            num_ref_images=info.get("num_ref_images", 0),
            resolution=info.get("resolution", 1024),
            cfg_enabled=info.get("cfg_enabled", False),
        ))
    return result


@app.post("/api/generate", response_model=Generation)
async def generate(payload: GenerateRequest, user_id: UUID = Depends(require_user)):
    if not _can_accept_generation(_active_generations):
        raise HTTPException(
            status_code=429,
            detail="Global generation queue is full. Try again later.",
        )

    gen_id = str(uuid4())
    _active_generations[gen_id] = {
        "user_id": user_id,
        "prompt": payload.prompt,
        "queued_at": time.time(),
        "started_at": None,
        "status": "queued",
        "num_inference_steps": payload.num_inference_steps,
        "num_ref_images": len(payload.images or []),
        "resolution": payload.resolution,
        "cfg_enabled": payload.true_cfg_scale > 1 and bool(payload.negative_prompt),
    }
    try:
        async with _generation_lock:
            active_info = _active_generations.get(gen_id)
            if active_info is not None:
                active_info["started_at"] = time.time()
                active_info["status"] = "running"

            image_bytes = await generate_image_bytes(
                payload.prompt,
                payload.images,
                payload.num_inference_steps,
                payload.true_cfg_scale,
                payload.negative_prompt,
                payload.resolution,
            )

        active_info = _active_generations.get(gen_id)
        if active_info is not None:
            active_info["status"] = "saving"

        image_path, public_url = upload_image(user_id, image_bytes)
        record = insert_generation(user_id, payload.prompt, image_path, public_url)
        return record
    except QwenImageError as exc:
        logger.exception("Qwen-Image error during generate")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SupabaseError as exc:
        logger.exception("Supabase error during generate")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unhandled error during generate")
        raise HTTPException(status_code=500, detail="Internal server error") from exc
    finally:
        _active_generations.pop(gen_id, None)


@app.post("/api/service/generate", response_model=ServiceImageResponse)
async def service_generate(request: Request, _: None = Depends(require_service_token)):
    """Generate untuk klien mesin (backend lokal Inkspire): stateless, tanpa Supabase.

    Satu endpoint untuk T2I (tanpa `images`) dan I2I (dengan `images`), memakai
    antrean admission dan lock inference yang sama dengan endpoint pengguna.
    Hasil PNG dikembalikan langsung dan tidak disimpan di MaPic.
    """
    body = await _read_limited_body(request, MAX_SERVICE_REQUEST_BYTES)
    try:
        payload = ServiceGenerateRequest.model_validate_json(body)
    except ValidationError as exc:
        # Bentuk 422 disamakan dengan validasi FastAPI biasa (`loc` diawali
        # "body", tanpa kunci `url`), tetapi nilai `input`/`ctx` dibuang supaya
        # respons error tidak menggemakan payload base64 yang baru ditolak.
        errors = exc.errors(include_url=False)
        for error in errors:
            error.pop("input", None)
            error.pop("ctx", None)
            error["loc"] = ("body", *error["loc"])
        raise RequestValidationError(errors) from exc

    if payload.resolution > QWEN_MAX_RESOLUTION:
        raise HTTPException(
            status_code=422,
            detail=f"Resolution {payload.resolution} exceeds this server's limit of {QWEN_MAX_RESOLUTION}",
        )

    _validate_service_images(payload.images)

    if not _can_accept_generation(_active_generations):
        raise HTTPException(
            status_code=429,
            detail="Global generation queue is full. Try again later.",
        )

    job_id = str(uuid4())
    # Metadata antrean sementara saja: tanpa prompt, gambar, atau identitas
    # pengguna. Slot dilepas di `finally` pada sukses, exception, timeout,
    # maupun pembatalan request.
    _active_generations[job_id] = {
        "kind": "service",
        "queued_at": time.time(),
        "started_at": None,
        "status": "queued",
    }
    try:
        async with _generation_lock:
            info = _active_generations.get(job_id)
            if info is not None:
                info["started_at"] = time.time()
                info["status"] = "running"

            image_bytes = await generate_image_bytes(
                payload.prompt,
                payload.images,
                payload.num_inference_steps,
                payload.true_cfg_scale,
                payload.negative_prompt,
                payload.resolution,
            )
        return {"data": [{"b64_json": base64.b64encode(image_bytes).decode("utf-8")}]}
    except QwenImageTimeoutError as exc:
        # Pesan downstream bisa memuat detail internal; cukup di log server.
        logger.error("Service generation timed out: %s", exc)
        raise HTTPException(status_code=504, detail="Generation timed out") from exc
    except QwenImageError as exc:
        logger.error("Service generation failed: %s", exc)
        raise HTTPException(status_code=502, detail="Generation failed") from exc
    except Exception as exc:
        logger.exception("Unhandled error during service generation")
        raise HTTPException(status_code=500, detail="Internal server error") from exc
    finally:
        _active_generations.pop(job_id, None)


@app.post("/api/remove-background", response_model=Generation)
async def remove_background(payload: RemoveBackgroundRequest, user_id: UUID = Depends(require_user)):
    if len(payload.image) > MAX_REMOVE_BACKGROUND_BASE64_CHARS:
        raise HTTPException(status_code=413, detail="Image payload too large")

    try:
        raw = base64.b64decode(payload.image, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Image is not valid base64") from exc

    if len(raw) > MAX_REMOVE_BACKGROUND_BYTES:
        raise HTTPException(status_code=413, detail="Image payload too large")

    try:
        with Image.open(BytesIO(raw)) as source:
            source.load()
            source_format = source.format
            width, height = source.size
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Image could not be read") from exc

    if source_format not in {"PNG", "JPEG"}:
        raise HTTPException(status_code=422, detail="Only PNG and JPEG images are supported")

    if (
        width <= 0
        or height <= 0
        or max(width, height) > MAX_REMOVE_BACKGROUND_SIDE
        or width * height > MAX_REMOVE_BACKGROUND_PIXELS
    ):
        raise HTTPException(
            status_code=422,
            detail=f"Image dimensions {width}x{height} exceed the supported range",
        )

    # Checked before inference so a busy worker costs the caller one request, and
    # before the await so the 429 is decided without queuing behind the lock.
    if _remove_background_lock.locked():
        raise HTTPException(
            status_code=429,
            detail="Background removal is busy with another image. Try again shortly.",
        )

    try:
        async with _remove_background_lock:
            png_bytes = await asyncio.to_thread(remove_background_service.remove_background_png, raw)
    except remove_background_service.ModelUnavailableError as exc:
        # The worker's message embeds local weight paths; keep it in the log only.
        logger.exception("Remove background model unavailable")
        raise HTTPException(status_code=503, detail="Background removal model is unavailable") from exc
    except remove_background_service.RemoveBackgroundError as exc:
        logger.exception("Remove background worker failed")
        raise HTTPException(status_code=502, detail="Background removal failed") from exc

    try:
        image_path, public_url = upload_image(user_id, png_bytes)
    except SupabaseError as exc:
        logger.exception("Supabase error during remove background upload")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        prompt = _history_prompt_for_cutout(_clean_source_label(payload.source_label))
        return insert_generation(user_id, prompt, image_path, public_url)
    except SupabaseError as exc:
        logger.exception("Supabase error during remove background insert")
        delete_stored_image(image_path)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/history/{user_id}", response_model=list[Generation])
async def history(user_id: UUID, current_user: UUID = Depends(require_user)):
    if user_id != current_user:
        raise HTTPException(status_code=403, detail="Cannot read another user's history")
    try:
        return fetch_history(user_id)
    except SupabaseError as exc:
        logger.exception("Supabase error during history")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unhandled error during history")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@app.delete("/api/history/{id}")
async def delete_history_item(id: UUID, user_id: UUID = Depends(require_user)):
    try:
        delete_generation(id, user_id)
        return {"ok": True}
    except GenerationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupabaseError as exc:
        logger.exception("Supabase error during delete")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unhandled error during delete")
        raise HTTPException(status_code=500, detail="Internal server error") from exc
