import asyncio
import base64
import logging

import httpx

try:
    from backend.config import QWEN_IMAGE_API_URL
except ModuleNotFoundError:
    from config import QWEN_IMAGE_API_URL

logger = logging.getLogger("mapic.qwen_image")

TIMEOUT_SECONDS = 3600  # Qwen-Image 2.1 at 2K; enabling CFG roughly doubles each step
MAX_RETRIES = 6
RETRY_DELAY = 10  # seconds between retries


class QwenImageError(Exception):
    pass


def _error_detail(response: httpx.Response) -> str:
    """Ambil pesan error dari body JSON inference server, apa pun bentuknya."""
    try:
        payload = response.json()
    except Exception:
        return response.text[:300]
    if isinstance(payload, dict):
        for key in ("error", "detail"):
            if payload.get(key):
                return str(payload[key])
    return str(payload)[:300]


async def get_health_status() -> str:
    url = QWEN_IMAGE_API_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{url}/health")
            resp.raise_for_status()
            return resp.json().get("status", "offline")
    except Exception as exc:
        logger.warning(f"Health check failed: {exc}")
        return "offline"

async def load_model() -> dict:
    url = QWEN_IMAGE_API_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=300) as client: # Timeout panjang untuk loading
        resp = await client.post(f"{url}/v1/system/load")
        resp.raise_for_status()
        return resp.json()

async def stream_load_model():
    url = QWEN_IMAGE_API_URL.rstrip("/")
    # Disable timeout for the stream as loading can take > 5 minutes
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", f"{url}/v1/system/load/stream") as response:
            async for line in response.aiter_lines():
                if line:
                    yield f"{line}\n\n"


async def unload_model() -> dict:
    url = QWEN_IMAGE_API_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{url}/v1/system/unload")
        resp.raise_for_status()
        return resp.json()


async def get_generation_status() -> dict:
    url = QWEN_IMAGE_API_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{url}/v1/generations/status")
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("Generation status check failed: %s", exc)
        return {"stage": "idle", "step": 0, "total_steps": 0}


async def get_load_state() -> dict:
    url = QWEN_IMAGE_API_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{url}/v1/system/load/state")
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("Load state check failed: %s", exc)
        return {"status": "offline", "segment_index": 0, "segment_progress": 0.0, "progress": 0, "message": ""}


async def generate_image_bytes(
    prompt: str,
    images: list[str] | None = None,
    num_inference_steps: int = 40,
    true_cfg_scale: float = 1.0,
    negative_prompt: str | None = None,
    resolution: int = 2048,
) -> bytes:
    url = QWEN_IMAGE_API_URL.rstrip("/")

    payload = {
        "prompt": prompt,
        "num_inference_steps": num_inference_steps,
        "true_cfg_scale": true_cfg_scale,
        "resolution": resolution,
    }

    if negative_prompt:
        payload["negative_prompt"] = negative_prompt

    if images:
        endpoint = f"{url}/v1/images/edits"
        payload["images"] = images
    else:
        endpoint = f"{url}/v1/images/generations"

    last_exc = None

    # Auto-load if unloaded
    current_status = await get_health_status()
    if current_status == "unloaded":
        logger.info("Model is unloaded. Auto-loading before generation...")
        await load_model()

    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                resp = await client.post(endpoint, json=payload)
                resp.raise_for_status()
                data = resp.json()
                images = data.get("data") or []
                if not images or "b64_json" not in images[0]:
                    raise QwenImageError(f"Respons Qwen-Image tidak berisi gambar: {str(data)[:200]}")
                return base64.b64decode(images[0]["b64_json"])
        except httpx.ConnectError as exc:
            last_exc = exc
            logger.warning("Qwen-Image server not ready, retry %d/%d in %ds", attempt + 1, MAX_RETRIES, RETRY_DELAY)
            await asyncio.sleep(RETRY_DELAY)
        except httpx.HTTPStatusError as exc:
            detail = _error_detail(exc.response)
            logger.error("Qwen-Image server returned %s: %s", exc.response.status_code, detail)
            raise QwenImageError(detail) from exc
        except QwenImageError:
            raise
        except Exception as exc:
            logger.exception("Qwen-Image request failed")
            raise QwenImageError(str(exc)) from exc

    raise QwenImageError(f"Qwen-Image server unavailable after {MAX_RETRIES} retries: {last_exc}") from last_exc
