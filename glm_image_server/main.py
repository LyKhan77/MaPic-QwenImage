import asyncio
import base64
import gc
import io
import logging
import math
import subprocess
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

# GPU indices from nvidia-smi (2026-05-06):
#   GPU 0 = RTX 5080 (16 GB, Blackwell)
#   GPU 1 = RTX 5080 (16 GB, Blackwell)
#   GPU 2 = RTX 4090 (24 GB, Ada Lovelace)
MAX_MEMORY = {
    2: "22GiB",    # RTX 4090 (Primary carrier)
    0: "14GiB",    # RTX 5080
    1: "14GiB",    # RTX 5080
    "cpu": "4GiB", # overflow safety net
}


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

    # RTX 5080 = Blackwell (sm_120) — needs PyTorch >= 2.6
    if num_gpus >= 2 and "sm_120" not in arch_list:
        logger.warning(
            "RTX 5080 detected but sm_120 not in compiled archs. "
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
            update_progress(15, "Loading pipeline weights (8-bit, 3-GPU)...")
            logger.info("Loading GLM-Image pipeline (8-bit quantized, 3-GPU)...")

            # 8-bit quantization for transformer + AR encoder — halves weight memory (~32 GB -> ~16 GB)
            # Full bf16 (~32 GB weights) doesn't fit with balanced split across 2x 16 GB GPUs
            quantization_config = PipelineQuantizationConfig(
                quant_backend="bitsandbytes_8bit",
                quant_kwargs={"load_in_8bit": True},
                components_to_quantize=["transformer", "vision_language_encoder"],
            )

            pipe = GlmImagePipeline.from_pretrained(
                "zai-org/GLM-Image",
                torch_dtype=torch.bfloat16,
                device_map="balanced",
                max_memory=MAX_MEMORY,
                quantization_config=quantization_config,
            )
            logger.info("GLM-Image pipeline loaded (8-bit, device_map=balanced, 3-GPU).")

            # Move VAE to GPU 2 (RTX 4090, 24 GB) — runs natively on GPU, no CPU roundtrips
            # Must detach accelerate hooks before moving, then re-register on new device
            update_progress(70, "Placing VAE on GPU 2 (RTX 4090)...")
            logger.info("Placing VAE on GPU 2 (cuda:2)...")
            if hasattr(pipe.vae, "_hf_hook"):
                from accelerate.hooks import remove_hook_from_module
                remove_hook_from_module(pipe.vae, recurse=True)
            pipe.vae = pipe.vae.to("cuda:2")

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
            update_progress(80, "Enabling memory optimizations...")
            try:
                if hasattr(pipe, "transformer") and hasattr(pipe.transformer, "enable_attention_slicing"):
                    pipe.transformer.enable_attention_slicing("auto")
                    logger.info("Transformer attention slicing enabled.")
                elif hasattr(pipe, "enable_attention_slicing"):
                    pipe.enable_attention_slicing("auto")
                    logger.info("Pipeline attention slicing enabled.")
            except Exception as exc:
                logger.warning("Attention slicing not available: %s", exc)

            # Enable Flash SDP + memory-efficient SDP for attention
            if hasattr(torch.backends.cuda, "enable_flash_sdp"):
                torch.backends.cuda.enable_flash_sdp(True)
                logger.info("Flash SDP enabled.")
            if hasattr(torch.backends.cuda, "enable_mem_efficient_sdp"):
                torch.backends.cuda.enable_mem_efficient_sdp(True)
                logger.info("Memory-efficient SDP enabled.")

            # torch.compile the transformer for faster diffusion denoising
            update_progress(85, "Compiling transformer...")
            try:
                torch.set_float32_matmul_precision("high")
                pipe.transformer.to(memory_format=torch.channels_last)
                pipe.transformer = torch.compile(pipe.transformer, mode="reduce-overhead")
                logger.info("Transformer compiled (reduce-overhead mode).")
            except Exception as exc:
                logger.warning("torch.compile not available or failed: %s", exc)

            global is_unloaded
            is_unloaded = False
            update_progress(95, "Finalizing...")
            # Set AR sampling params to model-recommended defaults
            pipe.vision_language_encoder.generation_config.temperature = 0.9
            pipe.vision_language_encoder.generation_config.top_p = 0.75
            pipe.vision_language_encoder.generation_config.do_sample = True
            logger.info("AR sampling config: temperature=0.9, top_p=0.75, do_sample=True")

            _log_device_map()
            _log_gpu_memory("after_load")
            update_progress(100, "Ready.")
            logger.info("GLM-Image pipeline ready (3-GPU, 8-bit, VAE on GPU 2).")
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
    num_inference_steps: int = 50
    guidance_scale: float = 1.5


class I2IRequest(BaseModel):
    prompt: str
    images: list[str]
    size: str = "1024x1024"
    response_format: str = "b64_json"
    num_inference_steps: int = 35
    guidance_scale: float = 1.5


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
                num_inference_steps=req.num_inference_steps,
                guidance_scale=req.guidance_scale,
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
                num_inference_steps=req.num_inference_steps,
                guidance_scale=req.guidance_scale,
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
