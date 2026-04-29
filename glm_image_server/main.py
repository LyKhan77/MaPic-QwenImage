import asyncio
import base64
import gc
import io
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import json
from fastapi.responses import StreamingResponse

last_request_time = time.time()
is_unloaded = True
is_loading = False
loading_progress = 0
loading_message = ""

def update_progress(prog: int, msg: str):
    global loading_progress, loading_message
    loading_progress = prog
    loading_message = msg

import torch
from diffusers import PipelineQuantizationConfig
from diffusers.pipelines.glm_image import GlmImagePipeline
from fastapi import FastAPI
from PIL import Image
from pydantic import BaseModel

logger = logging.getLogger("glm_image_server")
pipe: GlmImagePipeline | None = None
_executor = ThreadPoolExecutor(max_workers=1)
_inference_lock = asyncio.Lock()

MAX_MEMORY = {
    0: "23GiB",  # RTX 4090 (24 GB) — asymmetric allocation for headroom
    1: "13GiB",  # RTX 5080 (16 GB) — leave ~3 GB for peak activations
}


def _patch_vae_device():
    """Fix CUDA/CPU mismatch when device_map offloads VAE to CPU."""
    if pipe is None:
        return

    original_encode = pipe.vae.encode
    original_decode = pipe.vae.decode

    def patched_encode(x):
        vae_device = next(pipe.vae.parameters()).device
        orig_device = x.device
        x = x.to(device=vae_device)
        result = original_encode(x)
        if hasattr(result, "latent_dist") and hasattr(result.latent_dist, "parameters"):
            for attr in ["parameters", "mean", "logvar", "std", "var"]:
                if hasattr(result.latent_dist, attr):
                    val = getattr(result.latent_dist, attr)
                    if isinstance(val, torch.Tensor):
                        setattr(result.latent_dist, attr, val.to(orig_device))
        elif hasattr(result, "latents"):
            result.latents = result.latents.to(orig_device)
        return result

    def patched_decode(z, *args, **kwargs):
        vae_device = next(pipe.vae.parameters()).device
        orig_device = z.device
        z = z.to(device=vae_device)
        result = original_decode(z, *args, **kwargs)
        if isinstance(result, tuple):
            result = tuple(t.to(orig_device) if hasattr(t, "to") else t for t in result)
        return result

    pipe.vae.encode = patched_encode
    pipe.vae.decode = patched_decode


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
        update_progress(10, "Initializing loading...")
        logger.info("Loading GLM-Image pipeline across GPUs...")
        _log_gpu_memory("before_load")

        try:
            # 8-bit quantization to halve model weight memory (~32 GB -> ~16 GB)
            quantization_config = None
            try:
                quantization_config = PipelineQuantizationConfig(
                    quant_backend="bitsandbytes_8bit",
                    quant_kwargs={"load_in_8bit": True},
                    components_to_quantize=["transformer", "vision_language_encoder"],
                )
                logger.info("8-bit quantization config created.")
            except Exception as exc:
                logger.warning("Failed to create quantization config: %s", exc)

            try:
                update_progress(20, "Loading pipeline weights (this takes a while)...")
                pipe = GlmImagePipeline.from_pretrained(
                    "zai-org/GLM-Image",
                    torch_dtype=torch.bfloat16,
                    device_map="balanced",
                    max_memory=MAX_MEMORY,
                    quantization_config=quantization_config,
                )
                _patch_vae_device()
                logger.info("GLM-Image pipeline loaded with 8-bit quantization.")
            except Exception as exc:
                logger.warning("Quantized load failed (%s). Falling back to standard load...", exc)
                update_progress(20, "Loading standard weights (this takes a while)...")
                pipe = GlmImagePipeline.from_pretrained(
                    "zai-org/GLM-Image",
                    torch_dtype=torch.bfloat16,
                    device_map="balanced",
                    max_memory=MAX_MEMORY,
                )
                _patch_vae_device()
                logger.info("GLM-Image pipeline loaded (standard, no quantization).")

            # Offload VAE to CPU to free GPU VRAM for transformer activations
            update_progress(80, "Model loaded. Offloading VAE to CPU...")
            logger.info("Offloading VAE to CPU...")
            pipe.vae = pipe.vae.to("cpu")

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

            # Enable attention slicing on transformer to reduce activation memory
            update_progress(90, "Enabling memory optimizations...")
            try:
                if hasattr(pipe, "transformer") and hasattr(pipe.transformer, "enable_attention_slicing"):
                    pipe.transformer.enable_attention_slicing("auto")
                    logger.info("Transformer attention slicing enabled.")
                elif hasattr(pipe, "enable_attention_slicing"):
                    pipe.enable_attention_slicing("auto")
                    logger.info("Pipeline attention slicing enabled.")
            except Exception as exc:
                logger.warning("Attention slicing not available: %s", exc)

            # Enable Flash SDP for memory-efficient attention (PyTorch 2.0+)
            if hasattr(torch.backends.cuda, "enable_flash_sdp"):
                torch.backends.cuda.enable_flash_sdp(True)
                logger.info("Flash SDP enabled.")

            global is_unloaded
            is_unloaded = False
            update_progress(100, "Ready.")
            _log_gpu_memory("after_load")
            logger.info("GLM-Image pipeline ready (multi-GPU, VAE on CPU).")
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


app = FastAPI(title="GLM-Image Server", lifespan=lifespan)


class T2IRequest(BaseModel):
    prompt: str
    size: str = "1024x1024"
    response_format: str = "b64_json"


class I2IRequest(BaseModel):
    prompt: str
    images: list[str]
    size: str = "1024x1024"
    response_format: str = "b64_json"


def _snap_to_32(size: str) -> tuple[int, int]:
    parts = size.lower().split("x")
    w, h = int(parts[0]), int(parts[1])
    return (math.ceil(w / 32) * 32, math.ceil(h / 32) * 32)


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


@app.post("/v1/images/generations")
async def text_to_image(req: T2IRequest):
    async with _inference_lock:
        global last_request_time
        last_request_time = time.time()
        if pipe is None:
            return {"error": "Model failed to load"}

        width, height = _snap_to_32(req.size)
        logger.info("T2I: prompt=%r size=%dx%d", req.prompt[:80], width, height)
        result = await _run_inference(
            lambda: pipe(
                prompt=req.prompt,
                width=width,
                height=height,
                num_inference_steps=50,
                guidance_scale=1.5,
            )
        )
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

        width, height = _snap_to_32(req.size)
        ref_images = [_b64_to_pil(b).convert("RGB") for b in req.images]
        ref_images = [img.resize((width, height), Image.LANCZOS) for img in ref_images]
        logger.info("I2I: prompt=%r refs=%d size=%dx%d", req.prompt[:80], len(ref_images), width, height)
        result = await _run_inference(
            lambda: pipe(
                prompt=req.prompt,
                image=ref_images,
                height=height,
                width=width,
                num_inference_steps=35,
                guidance_scale=1.5,
            )
        )
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
