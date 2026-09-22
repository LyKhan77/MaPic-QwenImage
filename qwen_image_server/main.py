import asyncio
import base64
import io
import json
import logging
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from PIL import Image
from pydantic import BaseModel

from comfy_client import ComfyClient, ComfyError
from workflows import build_i2i, build_t2i

logger = logging.getLogger("qwen_image_server")

# ComfyUI yang menjalankan Qwen-Image 2.1 GGUF. Facade ini mempertahankan kontrak
# API lama (T2I/I2I, load/unload, stage tracking) supaya backend dan frontend
# tidak perlu diubah.
comfy = ComfyClient(os.getenv("COMFY_BASE_URL", "http://127.0.0.1:8188"))
_executor_lock = asyncio.Lock()
_inference_lock = asyncio.Lock()

MAX_RESOLUTION = int(os.getenv("QWEN_MAX_RESOLUTION", "2048"))
WARMUP_SIZE = 256
WARMUP_STEPS = 1

last_request_time = time.time()
is_unloaded = True
is_loading = False
loading_progress = 0
loading_message = ""


def update_progress(prog: int, msg: str):
    global loading_progress, loading_message
    loading_progress = prog
    loading_message = msg


# Thread-safe generation state for stage tracking
_gen_state = {"stage": "idle", "step": 0, "total_steps": 0}
_gen_lock = threading.Lock()


def update_gen_state(stage: str, step: int = 0, total_steps: int = 0):
    with _gen_lock:
        _gen_state.update({"stage": stage, "step": step, "total_steps": total_steps})


def get_gen_state():
    with _gen_lock:
        return dict(_gen_state)


async def _warmup():
    graph = build_t2i(
        prompt="warmup",
        steps=WARMUP_STEPS,
        width=WARMUP_SIZE,
        height=WARMUP_SIZE,
        resolution=WARMUP_SIZE,
        filename_prefix="mapic_warmup",
    )
    await comfy.run(graph)


async def load_model():
    """Pramuat model ke VRAM ComfyUI (ComfyUI memuat model saat job pertama)."""
    global is_loading, is_unloaded
    if is_loading:
        return
    is_loading = True
    try:
        update_progress(10, "Menghubungi ComfyUI...")
        await comfy.system_stats()
        update_progress(20, "Memuat model ke VRAM...")
        await _warmup()
        is_unloaded = False
        update_progress(95, "Finalizing...")
        update_progress(100, "Ready.")
        logger.info("Model siap di VRAM.")
    except Exception as exc:
        update_progress(0, f"Error: {exc}")
        logger.exception("Gagal memuat model")
        raise
    finally:
        is_loading = False


async def unload_model():
    global is_unloaded
    await comfy.free(unload_models=True, free_memory=True)
    is_unloaded = True
    logger.info("Model dilepas dari VRAM.")


def _mark_loaded():
    global is_unloaded
    is_unloaded = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Facade Qwen-Image 2.1 siap. ComfyUI: %s", comfy.base_url)
    yield


app = FastAPI(title="Qwen-Image 2.1 Server", lifespan=lifespan)

# Suppress access logs for successful polling GETs to reduce log noise
class _QuietPollingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if '"GET ' in msg and '200 OK' in msg:
            return False
        return True

logging.getLogger("uvicorn.access").addFilter(_QuietPollingFilter())


class T2IRequest(BaseModel):
    prompt: str
    negative_prompt: str | None = None
    true_cfg_scale: float = 1.0
    resolution: int = 1024
    size: str | None = None
    response_format: str = "b64_json"
    num_inference_steps: int = 40


class I2IRequest(BaseModel):
    prompt: str
    images: list[str]
    negative_prompt: str | None = None
    true_cfg_scale: float = 1.0
    resolution: int = 1024
    size: str | None = None
    response_format: str = "b64_json"
    num_inference_steps: int = 40


def _snap(value: int, multiple_of: int = 32) -> int:
    return max(multiple_of, value // multiple_of * multiple_of)


def _snap_to_32(size: str) -> tuple[int, int]:
    parts = size.lower().split("x")
    return (_snap(int(parts[0])), _snap(int(parts[1])))


def _size_from_reference(image: Image.Image, resolution: int) -> tuple[int, int]:
    """Ikuti aspect ratio gambar referensi, dengan luas mendekati resolution^2."""
    ratio = image.size[0] / image.size[1]
    area = resolution * resolution
    return (_snap(int((area * ratio) ** 0.5)), _snap(int((area / ratio) ** 0.5)))


def _effective_cfg(req: T2IRequest | I2IRequest) -> float:
    # Qwen-Image 2.1 disampel tanpa guidance; true_cfg_scale hanya berlaku
    # bersama negative prompt, dan menggandakan kerja tiap step.
    if req.true_cfg_scale > 1 and req.negative_prompt:
        return req.true_cfg_scale
    return 1.0


def _set_stage(stage: str, step: int = 0, total_steps: int = 0):
    update_gen_state(stage, step, total_steps)


def _pil_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _b64_to_pil(b64: str) -> Image.Image:
    data = base64.b64decode(b64)
    return Image.open(io.BytesIO(data))


@app.get("/health")
async def health():
    if is_loading:
        return {"status": "loading"}
    try:
        await comfy.system_stats()
    except Exception:
        return {"status": "offline"}
    return {"status": "unloaded" if is_unloaded else "ready"}


@app.get("/v1/system/load/stream")
async def api_load_model_stream():
    global last_request_time
    last_request_time = time.time()

    if is_unloaded and not is_loading:
        async def _run():
            try:
                await _executor_lock.acquire()
                try:
                    await load_model()
                finally:
                    _executor_lock.release()
            except Exception:
                pass

        asyncio.create_task(_run())

    async def event_generator():
        last_prog = -1
        last_msg = ""
        while True:
            if loading_progress != last_prog or loading_message != last_msg:
                last_prog = loading_progress
                last_msg = loading_message
                yield f"data: {json.dumps({'progress': last_prog, 'message': last_msg})}\n\n"
            else:
                # Send SSE comment as keep-alive ping
                yield ": ping\n\n"

            if not is_loading:
                if not is_unloaded and last_prog != 100:
                    yield f"data: {json.dumps({'progress': 100, 'message': 'Ready.'})}\n\n"
                elif is_unloaded:
                    yield f"data: {json.dumps({'progress': 0, 'message': loading_message or 'Failed to load model', 'error': True})}\n\n"
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/v1/system/load")
async def api_load_model():
    global last_request_time
    await _executor_lock.acquire()
    try:
        await load_model()
    finally:
        _executor_lock.release()
    last_request_time = time.time()
    return {"status": "ready"}


@app.post("/v1/system/unload")
async def api_unload_model():
    if not is_unloaded:
        await unload_model()
    return {"status": "unloaded"}


LOAD_SEGMENTS = [
    {"key": "preflight", "label": "Pre-flight checks", "range": (0, 14)},
    {"key": "weights", "label": "Loading weights", "range": (15, 79)},
    {"key": "optimize", "label": "Optimizations", "range": (80, 94)},
    {"key": "finalize", "label": "Finalizing", "range": (95, 100)},
]


@app.get("/v1/system/load/state")
async def api_load_state():
    if is_loading:
        seg_index = 0
        seg_progress = 0.0
        for i, seg in enumerate(LOAD_SEGMENTS):
            lo, hi = seg["range"]
            if loading_progress >= lo:
                seg_index = i
                if loading_progress <= hi:
                    seg_progress = (loading_progress - lo) / max(1, hi - lo)
        return {
            "status": "loading",
            "segment_index": seg_index,
            "segment_progress": round(seg_progress, 2),
            "progress": loading_progress,
            "message": loading_message,
        }
    if not is_unloaded:
        return {"status": "ready", "segment_index": 4, "segment_progress": 1.0, "progress": 100, "message": "Ready."}
    return {"status": "unloaded", "segment_index": 0, "segment_progress": 0.0, "progress": 0, "message": ""}


@app.get("/v1/generations/status")
async def generation_status():
    return get_gen_state()


@app.post("/v1/images/generations")
async def text_to_image(req: T2IRequest):
    async with _inference_lock:
        global last_request_time
        last_request_time = time.time()
        if req.resolution > MAX_RESOLUTION:
            return {"error": f"Resolution {req.resolution} exceeds this server's limit of {MAX_RESOLUTION}"}

        if req.size:
            width, height = _snap_to_32(req.size)
        else:
            width = height = req.resolution

        cfg_scale = _effective_cfg(req)
        logger.info("T2I: prompt=%r size=%dx%d steps=%d cfg=%.2f",
                    req.prompt[:80], width, height, req.num_inference_steps, cfg_scale)
        update_gen_state("warmup")

        graph = build_t2i(
            prompt=req.prompt,
            negative_prompt=req.negative_prompt or "",
            steps=req.num_inference_steps,
            cfg=cfg_scale,
            width=width,
            height=height,
            resolution=req.resolution,
            seed=uuid.uuid4().int % (2**31),
        )
        try:
            data = await comfy.run(graph, on_stage=_set_stage)
        except ComfyError as exc:
            logger.error("T2I gagal: %s", exc)
            return {"error": str(exc)}
        finally:
            update_gen_state("idle")

        _mark_loaded()
        return {"data": [{"b64_json": base64.b64encode(data).decode("utf-8")}]}


@app.post("/v1/images/edits")
async def image_to_image(req: I2IRequest):
    async with _inference_lock:
        global last_request_time
        last_request_time = time.time()
        if req.resolution > MAX_RESOLUTION:
            return {"error": f"Resolution {req.resolution} exceeds this server's limit of {MAX_RESOLUTION}"}
        if not req.images:
            return {"error": "At least one reference image is required"}
        if len(req.images) > 10:
            return {"error": "Qwen-Image 2.1 supports at most 10 reference images"}

        try:
            ref_images = [_b64_to_pil(b).convert("RGB") for b in req.images]
        except Exception as exc:
            return {"error": f"Gambar referensi tidak bisa dibaca: {exc}"}

        if req.size:
            width, height = _snap_to_32(req.size)
        else:
            width, height = _size_from_reference(ref_images[0], req.resolution)

        cfg_scale = _effective_cfg(req)
        logger.info("I2I: prompt=%r refs=%d size=%dx%d steps=%d cfg=%.2f",
                    req.prompt[:80], len(ref_images), width, height, req.num_inference_steps, cfg_scale)
        update_gen_state("warmup")

        try:
            names = []
            for image in ref_images:
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                names.append(await comfy.upload_image(buf.getvalue(), f"mapic_ref_{uuid.uuid4().hex[:10]}.png"))

            graph = build_i2i(
                prompt=req.prompt,
                image_names=names,
                negative_prompt=req.negative_prompt or "",
                steps=req.num_inference_steps,
                cfg=cfg_scale,
                width=width,
                height=height,
                resolution=req.resolution,
                seed=uuid.uuid4().int % (2**31),
            )
            data = await comfy.run(graph, on_stage=_set_stage)
        except ComfyError as exc:
            logger.error("I2I gagal: %s", exc)
            return {"error": str(exc)}
        finally:
            update_gen_state("idle")

        _mark_loaded()
        return {"data": [{"b64_json": base64.b64encode(data).decode("utf-8")}]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=30000)
