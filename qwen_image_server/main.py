import asyncio
import base64
import gc
import io
import json
import logging
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import torch
from diffusers import QwenImage21Pipeline
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from PIL import Image
from pydantic import BaseModel

logger = logging.getLogger("qwen_image_server")
pipe: QwenImage21Pipeline | None = None
_executor = ThreadPoolExecutor(max_workers=1)
_inference_lock = asyncio.Lock()

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

STAGE_NAMES = ["warmup", "encoding", "diffusion", "decoding"]


def update_gen_state(stage: str, step: int = 0, total_steps: int = 0):
    with _gen_lock:
        _gen_state.update({"stage": stage, "step": step, "total_steps": total_steps})


def get_gen_state():
    with _gen_lock:
        return dict(_gen_state)


def make_diffusion_callback(total_steps: int):
    def callback(pipeline, step_index, t, callback_kwargs):
        update_gen_state("diffusion", step=step_index + 1, total_steps=total_steps)
        return callback_kwargs
    return callback


def _parse_max_memory(raw: str) -> dict:
    # accelerate expects integer GPU indices, but JSON object keys always come back as strings.
    parsed = json.loads(raw)
    return {int(k) if str(k).isdigit() else k: v for k, v in parsed.items()}


# Qwen-Image 2.1: 7B single-stream DiT + Qwen3-VL 8B text encoder + 64-channel VAE.
# QWEN_MAX_MEMORY drives accelerate's balanced sharding across the available GPUs.
MAX_MEMORY = _parse_max_memory(os.getenv("QWEN_MAX_MEMORY", '{"cpu": "8GiB"}'))
# CPU offload skips per-GPU sharding and streams modules on demand: less VRAM, much slower.
USE_CPU_OFFLOAD = os.getenv("QWEN_CPU_OFFLOAD", "0") == "1"
# Low-VRAM hosts cap the output resolution so oversized requests fail fast instead of OOM.
MAX_RESOLUTION = int(os.getenv("QWEN_MAX_RESOLUTION", "2048"))


def _preflight_check():
    """Verify PyTorch supports all GPU architectures in the system."""
    arch_list = torch.cuda.get_arch_list()
    num_gpus = torch.cuda.device_count()
    logger.info("PyTorch %s | CUDA %s | %d GPU(s)", torch.__version__, torch.version.cuda, num_gpus)
    logger.info("Compiled archs: %s", arch_list)

    for i in range(num_gpus):
        props = torch.cuda.get_device_properties(i)
        logger.info("GPU %d: %s | %.0f MB | SM %d.%d",
                     i, props.name, props.total_memory / 1024**2,
                     props.major, props.minor)

    # Blackwell (sm_120) needs PyTorch >= 2.6 with CUDA 12.8
    has_blackwell = any(torch.cuda.get_device_properties(i).major == 12 for i in range(num_gpus))
    if has_blackwell and "sm_120" not in arch_list:
        logger.warning(
            "Blackwell (sm_120) GPU detected but sm_120 not in compiled archs. "
            "Upgrade PyTorch to >= 2.6 with CUDA 12.8 for native Blackwell support."
        )


def _log_gpu_topology():
    """Log PCIe topology for debugging inter-GPU bandwidth."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "topo", "-m"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            logger.info("GPU Topology:\n%s", result.stdout.strip())
    except Exception as exc:
        logger.warning("Could not query GPU topology: %s", exc)


def _log_device_map():
    """Log per-GPU parameter distribution after model load."""
    if pipe is None:
        return
    seen = {}
    for module_name in pipe.config.keys():
        module = getattr(pipe, module_name, None)
        if module is None:
            continue
        if hasattr(module, "parameters"):
            for param in module.parameters():
                dev = str(param.device)
                seen[dev] = seen.get(dev, 0) + param.numel()
    if seen:
        logger.info("Device map (parameter distribution):")
        for dev in sorted(seen):
            cnt = seen[dev]
            logger.info("  %s: %.2fB params (%.2f GB in bf16)", dev, cnt / 1e9, cnt * 2 / 1e9)


def _log_gpu_memory(label: str = ""):
    """Log current GPU memory usage for diagnostics."""
    if not torch.cuda.is_available():
        return
    prefix = f"{label} " if label else ""
    for i in range(torch.cuda.device_count()):
        allocated = torch.cuda.memory_allocated(i) / 1024**3
        reserved = torch.cuda.memory_reserved(i) / 1024**3
        total = torch.cuda.get_device_properties(i).total_memory / 1024**3
        logger.info(
            "%sGPU %d: %.2f GB allocated / %.2f GB reserved / %.2f GB total",
            prefix, i, allocated, reserved, total
        )


def load_model():
    global pipe, is_loading
    if pipe is None:
        is_loading = True
        update_progress(5, "Pre-flight checks...")
        _preflight_check()
        _log_gpu_topology()
        _log_gpu_memory("before_load")

        try:
            update_progress(15, "Loading pipeline weights (bf16)...")
            logger.info("Loading Qwen-Image 2.1 pipeline...")

            if USE_CPU_OFFLOAD:
                pipe = QwenImage21Pipeline.from_pretrained(
                    "Qwen/Qwen-Image-2.1",
                    torch_dtype=torch.bfloat16,
                )
                pipe.enable_model_cpu_offload()
                logger.info("Qwen-Image 2.1 loaded (model CPU offload).")
            else:
                pipe = QwenImage21Pipeline.from_pretrained(
                    "Qwen/Qwen-Image-2.1",
                    torch_dtype=torch.bfloat16,
                    device_map="balanced",
                    max_memory=MAX_MEMORY,
                )
                logger.info("Qwen-Image 2.1 loaded (device_map=balanced).")

            # Enable VAE slicing & tiling to reduce peak memory during encode/decode
            try:
                pipe.vae.enable_slicing()
                logger.info("VAE slicing enabled.")
            except Exception as exc:
                logger.warning("VAE slicing not available: %s", exc)

            try:
                pipe.vae.enable_tiling()
                logger.info("VAE tiling enabled.")
            except Exception as exc:
                logger.warning("VAE tiling not available: %s", exc)

            update_progress(80, "Enabling memory optimizations...")

            # Enable Flash SDP + memory-efficient SDP for attention
            if hasattr(torch.backends.cuda, "enable_flash_sdp"):
                torch.backends.cuda.enable_flash_sdp(True)
                logger.info("Flash SDP enabled.")
            if hasattr(torch.backends.cuda, "enable_mem_efficient_sdp"):
                torch.backends.cuda.enable_mem_efficient_sdp(True)
                logger.info("Memory-efficient SDP enabled.")

            global is_unloaded
            is_unloaded = False
            update_progress(95, "Finalizing...")

            _log_device_map()
            _log_gpu_memory("after_load")
            update_progress(100, "Ready.")
            logger.info("Qwen-Image 2.1 pipeline ready.")
        except Exception as exc:
            update_progress(0, f"Error: {exc}")
            raise
        finally:
            is_loading = False


def unload_model():
    global pipe, is_unloaded
    if pipe is not None:
        logger.info("Unloading model to free VRAM...")
        pipe = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        is_unloaded = True
        logger.info("Model unloaded. VRAM freed.")


async def idle_monitor():
    global last_request_time, is_unloaded
    idle_timeout = 3600  # 1 jam
    while True:
        await asyncio.sleep(60)  # Cek setiap 1 menit
        if not is_unloaded and pipe is not None:
            if time.time() - last_request_time > idle_timeout:
                logger.info(f"Model idle for > {idle_timeout}s. Auto-unloading...")
                unload_model()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(idle_monitor())
    yield
    task.cancel()


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
    resolution: int = 2048
    size: str | None = None
    response_format: str = "b64_json"
    num_inference_steps: int = 40


class I2IRequest(BaseModel):
    prompt: str
    images: list[str]
    negative_prompt: str | None = None
    true_cfg_scale: float = 1.0
    resolution: int = 2048
    size: str | None = None
    response_format: str = "b64_json"
    num_inference_steps: int = 40


def _snap_to_32(size: str) -> tuple[int, int]:
    parts = size.lower().split("x")
    w, h = int(parts[0]), int(parts[1])
    multiple_of = 32
    return (max(multiple_of, w // multiple_of * multiple_of),
            max(multiple_of, h // multiple_of * multiple_of))


def _effective_cfg(req: T2IRequest | I2IRequest) -> float:
    # Qwen-Image 2.1 samples without guidance by default: true_cfg_scale only takes effect
    # together with a negative prompt, and it doubles the work per denoising step.
    if req.true_cfg_scale > 1 and req.negative_prompt:
        return req.true_cfg_scale
    return 1.0


def _run_inference(fn):
    """Run blocking pipe() call in thread pool so event loop stays responsive."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(_executor, fn)


@app.get("/health")
async def health():
    if is_loading:
        return {"status": "loading"}
    if is_unloaded:
        return {"status": "unloaded"}
    if pipe is not None:
        return {"status": "ready"}
    return {"status": "loading"}



@app.get("/v1/system/load/stream")
async def api_load_model_stream():
    global is_unloaded, last_request_time
    last_request_time = time.time()
    
    if is_unloaded or pipe is None:
        if not is_loading:
            asyncio.get_event_loop().run_in_executor(_executor, load_model)
            
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
                if pipe is not None and last_prog != 100:
                    yield f"data: {json.dumps({'progress': 100, 'message': 'Ready.'})}\n\n"
                elif pipe is None:
                    # Error or unloading during load
                    yield f"data: {json.dumps({'progress': 0, 'message': loading_message or 'Failed to load model', 'error': True})}\n\n"
                break
                
            await asyncio.sleep(0.5)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/v1/system/load")
async def api_load_model():
    global is_unloaded, last_request_time
    if is_unloaded or pipe is None:
        # Run blocking load in executor to keep event loop free
        await _run_inference(load_model)
        last_request_time = time.time()
    return {"status": "ready"}


@app.post("/v1/system/unload")
async def api_unload_model():
    if not is_unloaded:
        unload_model()
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
    if pipe is not None and not is_unloaded:
        return {"status": "ready", "segment_index": 4, "segment_progress": 1.0, "progress": 100, "message": "Ready."}
    if is_unloaded:
        return {"status": "unloaded", "segment_index": 0, "segment_progress": 0.0, "progress": 0, "message": ""}
    return {"status": "loading", "segment_index": 0, "segment_progress": 0.0, "progress": 0, "message": "Starting..."}


@app.get("/v1/generations/status")
async def generation_status():
    return get_gen_state()


@app.post("/v1/images/generations")
async def text_to_image(req: T2IRequest):
    async with _inference_lock:
        global last_request_time
        last_request_time = time.time()
        if pipe is None:
            return {"error": "Model failed to load"}
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

        def run():
            update_gen_state("encoding")
            result = pipe(
                prompt=req.prompt,
                negative_prompt=req.negative_prompt,
                true_cfg_scale=cfg_scale,
                width=width,
                height=height,
                output_resolution=req.resolution,
                num_inference_steps=req.num_inference_steps,
                callback_on_step_end=make_diffusion_callback(req.num_inference_steps),
                callback_on_step_end_tensor_inputs=["latents"],
            )
            update_gen_state("decoding")
            return result

        result = await _run_inference(run)
        update_gen_state("idle")
        img: Image.Image = result.images[0]
        b64 = _pil_to_b64(img)
        return {"data": [{"b64_json": b64}]}


@app.post("/v1/images/edits")
async def image_to_image(req: I2IRequest):
    async with _inference_lock:
        global last_request_time
        last_request_time = time.time()
        if pipe is None:
            return {"error": "Model failed to load"}
        if req.resolution > MAX_RESOLUTION:
            return {"error": f"Resolution {req.resolution} exceeds this server's limit of {MAX_RESOLUTION}"}

        if not req.images:
            return {"error": "At least one reference image is required"}
        if len(req.images) > 10:
            return {"error": "Qwen-Image 2.1 supports at most 10 reference images"}

        # Condition images are handed over untouched: the pipeline resizes each one into its
        # own aspect-ratio bucket before the text encoder and the VAE read them.
        ref_images = [_b64_to_pil(b).convert("RGB") for b in req.images]

        width = height = None
        if req.size:
            width, height = _snap_to_32(req.size)

        cfg_scale = _effective_cfg(req)
        logger.info("I2I: prompt=%r refs=%d size=%s steps=%d cfg=%.2f",
                    req.prompt[:80], len(ref_images), req.size or f"auto@{req.resolution}",
                    req.num_inference_steps, cfg_scale)
        update_gen_state("warmup")

        def run():
            update_gen_state("encoding")
            result = pipe(
                prompt=req.prompt,
                image=ref_images,
                negative_prompt=req.negative_prompt,
                true_cfg_scale=cfg_scale,
                width=width,
                height=height,
                output_resolution=req.resolution,
                num_inference_steps=req.num_inference_steps,
                callback_on_step_end=make_diffusion_callback(req.num_inference_steps),
                callback_on_step_end_tensor_inputs=["latents"],
            )
            update_gen_state("decoding")
            return result

        result = await _run_inference(run)
        update_gen_state("idle")
        img: Image.Image = result.images[0]
        b64 = _pil_to_b64(img)
        return {"data": [{"b64_json": b64}]}


def _pil_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _b64_to_pil(b64: str) -> Image.Image:
    data = base64.b64decode(b64)
    return Image.open(io.BytesIO(data))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=30000)
