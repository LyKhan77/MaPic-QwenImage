import asyncio
import base64
import logging

import httpx

try:
    from backend.config import GLM_IMAGE_API_URL
except ModuleNotFoundError:
    from config import GLM_IMAGE_API_URL

logger = logging.getLogger("mapic.glm_image")

TIMEOUT_SECONDS = 14400  # GLM-Image is slow with CPU offload (~10-15 min)
MAX_RETRIES = 6
RETRY_DELAY = 10  # seconds between retries


class GlmImageError(Exception):
    pass


async def get_health_status() -> str:
    url = GLM_IMAGE_API_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{url}/health")
            resp.raise_for_status()
            return resp.json().get("status", "offline")
    except Exception as exc:
        logger.warning(f"Health check failed: {exc}")
        return "offline"

async def load_model() -> dict:
    url = GLM_IMAGE_API_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=300) as client: # Timeout panjang untuk loading
        resp = await client.post(f"{url}/v1/system/load")
        resp.raise_for_status()
        return resp.json()

async def stream_load_model():
    url = GLM_IMAGE_API_URL.rstrip("/")
    # Disable timeout for the stream as loading can take > 5 minutes
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", f"{url}/v1/system/load/stream") as response:
            async for line in response.aiter_lines():
                if line:
                    yield f"{line}\n\n"


async def unload_model() -> dict:
    url = GLM_IMAGE_API_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{url}/v1/system/unload")
        resp.raise_for_status()
        return resp.json()


async def get_generation_status() -> dict:
    url = GLM_IMAGE_API_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{url}/v1/generations/status")
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        logger.warning("Generation status check failed: %s", exc)
        return {"stage": "idle", "step": 0, "total_steps": 0}


async def generate_image_bytes(prompt: str, images: list[str] | None = None, num_inference_steps: int = 50, guidance_scale: float = 1.5) -> bytes:
    url = GLM_IMAGE_API_URL.rstrip("/")

    payload = {
        "prompt": prompt,
        "num_inference_steps": num_inference_steps,
        "guidance_scale": guidance_scale,
    }

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
                b64 = data["data"][0]["b64_json"]
                return base64.b64decode(b64)
        except httpx.ConnectError as exc:
            last_exc = exc
            logger.warning("GLM-Image server not ready, retry %d/%d in %ds", attempt + 1, MAX_RETRIES, RETRY_DELAY)
            await asyncio.sleep(RETRY_DELAY)
        except httpx.HTTPStatusError as exc:
            logger.exception("GLM-Image server returned %s", exc.response.status_code)
            raise GlmImageError(f"GLM-Image error: {exc.response.text}") from exc
        except Exception as exc:
            logger.exception("GLM-Image request failed")
            raise GlmImageError(str(exc)) from exc

    raise GlmImageError(f"GLM-Image server unavailable after {MAX_RETRIES} retries: {last_exc}") from last_exc
