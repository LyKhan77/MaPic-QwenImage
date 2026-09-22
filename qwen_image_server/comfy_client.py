"""Klien HTTP + WebSocket untuk ComfyUI yang menjalankan Qwen-Image 2.1 (GGUF)."""

import asyncio
import json
import logging
import uuid

import httpx
import websockets

logger = logging.getLogger("qwen_image_server.comfy")

# Node ComfyUI -> stage yang dikenal frontend (warmup/encoding/diffusion/decoding).
NODE_STAGES = {
    "TextEncodeQwenImage21": "encoding",
    "KSampler": "diffusion",
    "VAEDecode": "decoding",
}


class ComfyError(Exception):
    pass


class ComfyClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        ws_scheme = "wss" if self.base_url.startswith("https") else "ws"
        host = self.base_url.split("://", 1)[-1]
        self.ws_url = f"{ws_scheme}://{host}/ws"
        self.client_id = str(uuid.uuid4())

    async def system_stats(self, timeout: float = 5.0) -> dict:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{self.base_url}/system_stats")
            resp.raise_for_status()
            return resp.json()

    async def submit(self, graph: dict) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.base_url}/prompt",
                json={"prompt": graph, "client_id": self.client_id},
            )
        if resp.status_code != 200:
            raise ComfyError(f"ComfyUI menolak workflow ({resp.status_code}): {resp.text[:400]}")
        data = resp.json()
        if data.get("node_errors"):
            raise ComfyError(f"Workflow tidak valid: {json.dumps(data['node_errors'])[:400]}")
        return data["prompt_id"]

    async def upload_image(self, data: bytes, filename: str) -> str:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{self.base_url}/upload/image",
                files={"image": (filename, data, "image/png")},
                data={"overwrite": "true"},
            )
        if resp.status_code != 200:
            raise ComfyError(f"Gagal unggah gambar referensi: {resp.text[:300]}")
        info = resp.json()
        name = info.get("name", filename)
        subfolder = info.get("subfolder") or ""
        return f"{subfolder}/{name}" if subfolder else name

    async def fetch_image(self, filename: str, subfolder: str = "", kind: str = "output", timeout: float = 600) -> bytes:
        params = {"filename": filename, "subfolder": subfolder, "type": kind}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{self.base_url}/view", params=params)
        if resp.status_code != 200:
            raise ComfyError(f"Gagal mengambil gambar hasil ({resp.status_code})")
        return resp.content

    async def free(self, unload_models: bool = True, free_memory: bool = True) -> None:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.base_url}/free",
                json={"unload_models": unload_models, "free_memory": free_memory},
            )
        if resp.status_code != 200:
            raise ComfyError(f"Gagal membebaskan memori ComfyUI ({resp.status_code})")

    async def _history(self, prompt_id: str) -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(f"{self.base_url}/history/{prompt_id}")
            resp.raise_for_status()
            return resp.json()

    async def run(self, graph: dict, on_stage=None, idle_timeout: float = 3600) -> bytes:
        """Kirim graph, ikuti progres lewat WebSocket, kembalikan byte gambar hasil."""
        node_types = {nid: node.get("class_type", "") for nid, node in graph.items()}
        prompt_id = await self.submit(graph)
        logger.info("ComfyUI job dikirim: %s (%d node)", prompt_id, len(graph))

        def report(stage: str, step: int = 0, total: int = 0):
            if on_stage:
                on_stage(stage, step, total)

        try:
            async with websockets.connect(
                f"{self.ws_url}?clientId={self.client_id}",
                max_size=None,
                ping_interval=None,
                open_timeout=30,
            ) as ws:
                while True:
                    message = json.loads(await asyncio.wait_for(ws.recv(), timeout=idle_timeout))
                    mtype = message.get("type")
                    data = message.get("data") or {}
                    if data.get("prompt_id") not in (None, prompt_id):
                        continue
                    if mtype == "executing":
                        node = data.get("node")
                        if node is None:
                            break
                        report(NODE_STAGES.get(node_types.get(node, ""), "warmup"))
                    elif mtype == "progress":
                        report("diffusion", int(data.get("value") or 0), int(data.get("max") or 0))
                    elif mtype == "execution_error":
                        raise ComfyError(data.get("exception_message") or "ComfyUI gagal mengeksekusi workflow")
        except asyncio.TimeoutError as exc:
            raise ComfyError("ComfyUI tidak mengirim progres selama batas waktu") from exc

        entry = (await self._history(prompt_id)).get(prompt_id) or {}
        status = (entry.get("status") or {}).get("status_str")
        if status != "success":
            messages = (entry.get("status") or {}).get("messages") or []
            detail = json.dumps(messages)[-400:] if messages else "tidak ada detail"
            raise ComfyError(f"ComfyUI melaporkan status '{status}': {detail}")

        for output in (entry.get("outputs") or {}).values():
            for image in output.get("images") or []:
                return await self.fetch_image(
                    image["filename"], image.get("subfolder", ""), image.get("type", "output")
                )
        raise ComfyError("ComfyUI selesai tanpa menghasilkan gambar")
