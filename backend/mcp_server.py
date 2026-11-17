"""MCP Streamable HTTP (JSON-RPC 2.0) server untuk tool Image Generator & Background Remover MaPic."""

import base64
import json
import logging
from collections.abc import Awaitable, Callable
from io import BytesIO
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import ValidationError

try:
    from backend.schemas import ServiceGenerateRequest, ServiceRemoveBackgroundRequest
except ModuleNotFoundError:
    from schemas import ServiceGenerateRequest, ServiceRemoveBackgroundRequest

logger = logging.getLogger("mapic.mcp")

SUPPORTED_PROTOCOL_VERSIONS = ("2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL_VERSION = "2025-03-26"
SERVER_INFO = {"name": "mapic-mcp", "version": "1.0.0"}
SERVER_INSTRUCTIONS = (
    "MaPic local image studio on LAN. Use `generate_image` for text-to-image or "
    "image-to-image (up to 10 base64 PNG/JPEG reference images) and `remove_background` "
    "for fast CPU background removal returning a transparent RGBA PNG."
)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "generate_image",
        "description": (
            "Generate an image from a text prompt (T2I) or edit/combine up to 10 reference "
            "images (I2I) using Qwen-Image 2.1. Returns a PNG image."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 2000,
                    "description": "Detailed visual prompt. Put exact rendered text in quotes.",
                },
                "images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 10,
                    "description": "Optional base64-encoded PNG/JPEG reference images (no data-URL prefix, <= 2 MiB each).",
                },
                "negative_prompt": {
                    "type": "string",
                    "maxLength": 2000,
                    "description": "Elements to avoid. Required for true_cfg_scale > 1.0 to take effect.",
                },
                "true_cfg_scale": {
                    "type": "number",
                    "minimum": 1.0,
                    "maximum": 3.0,
                    "default": 1.0,
                    "description": "Classifier-free guidance scale (1.0 disables guidance; >1.0 doubles step time).",
                },
                "num_inference_steps": {
                    "type": "integer",
                    "minimum": 20,
                    "maximum": 75,
                    "default": 40,
                    "description": "Number of diffusion denoising steps (default 40).",
                },
                "resolution": {
                    "type": "integer",
                    "enum": [1024, 2048],
                    "default": 1024,
                    "description": "Target output resolution (1024 on 16 GB hosts).",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "remove_background",
        "description": (
            "Remove the background from one PNG or JPEG image on CPU (independent of GPU queue) "
            "and return a transparent RGBA PNG."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "image": {
                    "type": "string",
                    "description": "Base64-encoded PNG or JPEG image without data-URL prefix (<= 2 MiB, <= 2048 px).",
                },
            },
            "required": ["image"],
        },
    },
    {
        "name": "get_model_status",
        "description": "Check Qwen-Image readiness, active GPU node, and free VRAM per GPU worker.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def _rpc_result(req_id: Any, result: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})


def _rpc_error(req_id: Any, code: int, message: str, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}},
    )


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _png_dimensions(png_bytes: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(png_bytes)) as img:
            return img.size
    except Exception:
        return (0, 0)


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors(include_url=False):
        loc = ".".join(str(p) for p in err.get("loc", ())) or "arguments"
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    return "; ".join(parts) or "Invalid tool arguments"


async def handle_mcp_request(
    request: Request,
    *,
    raw_body: bytes,
    run_generate: Callable[[ServiceGenerateRequest], Awaitable[bytes]],
    run_remove_background: Callable[[str], Awaitable[bytes]],
    get_status: Callable[[], Awaitable[dict[str, Any]]],
) -> Response:
    """Proses satu pesan MCP Streamable HTTP JSON-RPC 2.0 secara stateless."""
    try:
        payload = json.loads(raw_body)
    except Exception:
        return _rpc_error(None, -32700, "Parse error: invalid JSON", status_code=400)

    if not isinstance(payload, dict) or not isinstance(payload.get("method"), str):
        return _rpc_error(payload.get("id") if isinstance(payload, dict) else None, -32600, "Invalid Request", status_code=400)

    method: str = payload["method"]
    req_id = payload.get("id")
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}

    # JSON-RPC notifications (tidak punya `id`) dibalas 202 Accepted tanpa body.
    if req_id is None or method.startswith("notifications/"):
        return Response(status_code=202)

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
        return _rpc_result(
            req_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": SERVER_INSTRUCTIONS,
            },
        )

    if method == "ping":
        return _rpc_result(req_id, {})

    if method == "tools/list":
        return _rpc_result(req_id, {"tools": TOOLS})

    if method != "tools/call":
        return _rpc_error(req_id, -32601, f"Method not found: {method}")

    tool_name = params.get("name")
    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(tool_name, str) or not isinstance(arguments, dict):
        return _rpc_error(req_id, -32602, "Invalid params: expected tool name and arguments object")

    if tool_name not in {"generate_image", "remove_background", "get_model_status"}:
        return _rpc_error(req_id, -32602, f"Unknown tool: {tool_name}")

    try:
        if tool_name == "generate_image":
            req = ServiceGenerateRequest.model_validate(arguments)
            png_bytes = await run_generate(req)
            width, height = _png_dimensions(png_bytes)
            refs = len(req.images or [])
            return _rpc_result(
                req_id,
                {
                    "content": [
                        {"type": "image", "data": base64.b64encode(png_bytes).decode("utf-8"), "mimeType": "image/png"},
                        {
                            "type": "text",
                            "text": f"Generated {width}x{height} PNG image (steps={req.num_inference_steps}, refs={refs}).",
                        },
                    ],
                    "isError": False,
                },
            )

        if tool_name == "remove_background":
            req = ServiceRemoveBackgroundRequest.model_validate(arguments)
            png_bytes = await run_remove_background(req.image)
            width, height = _png_dimensions(png_bytes)
            return _rpc_result(
                req_id,
                {
                    "content": [
                        {"type": "image", "data": base64.b64encode(png_bytes).decode("utf-8"), "mimeType": "image/png"},
                        {"type": "text", "text": f"Background removed -> {width}x{height} transparent PNG."},
                    ],
                    "isError": False,
                },
            )

        status_data = await get_status()
        return _rpc_result(
            req_id,
            {
                "content": [{"type": "text", "text": json.dumps(status_data, indent=2)}],
                "isError": False,
            },
        )
    except ValidationError as exc:
        return _rpc_result(req_id, _tool_error(_validation_message(exc)))
    except HTTPException as exc:
        return _rpc_result(req_id, _tool_error(str(exc.detail)))
    except Exception as exc:
        logger.exception("Unhandled error in MCP tool %s", tool_name)
        return _rpc_result(req_id, _tool_error("Internal server error"))
