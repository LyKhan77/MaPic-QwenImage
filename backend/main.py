import asyncio
import base64
import binascii
import logging
import time
from io import BytesIO
from uuid import UUID, uuid4

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
import uvicorn.logging

try:
    from backend.auth import require_user
    from backend.config import CORS_ORIGINS, QWEN_IMAGE_API_URL
    from backend.schemas import ActiveGeneration, GenerateRequest, Generation, RemoveBackgroundRequest
    from backend.services import remove_background_service
    from backend.services.qwen_image_service import QwenImageError, generate_image_bytes, get_generation_status, get_health_status, get_load_state, load_model, unload_model
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
    from auth import require_user
    from config import CORS_ORIGINS, QWEN_IMAGE_API_URL
    from schemas import ActiveGeneration, GenerateRequest, Generation, RemoveBackgroundRequest
    from services import remove_background_service
    from services.qwen_image_service import QwenImageError, generate_image_bytes, get_generation_status, get_health_status, get_load_state, load_model, unload_model
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


def _can_accept_generation(active_generations: dict[str, dict]) -> bool:
    return len(active_generations) < MAX_GLOBAL_GENERATIONS

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
        return insert_generation(user_id, REMOVE_BACKGROUND_PROMPT, image_path, public_url)
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
