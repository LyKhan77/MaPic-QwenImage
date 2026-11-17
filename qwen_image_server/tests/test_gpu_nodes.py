import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

# qwen_image_server/main.py mengimpor `comfy_client` dan `workflows` secara
# top-level (bukan relatif), sesuai cara uvicorn dijalankan di container.
QWEN_DIR = Path(__file__).resolve().parents[1]
if str(QWEN_DIR) not in sys.path:
    sys.path.insert(0, str(QWEN_DIR))

import main as qwen_main  # noqa: E402


def _fake_stats(name="cuda:0 NVIDIA GeForce RTX 5080 : cudaMallocAsync", total=16 * 1024**3, free=15 * 1024**3):
    return {
        "system": {"os": "linux"},
        "devices": [{"name": name, "type": "cuda", "index": 0, "vram_total": total, "vram_free": free}],
    }


def _make_worker(online=True, name="cuda:0 NVIDIA GeForce RTX 5080 : cudaMallocAsync", free=15 * 1024**3):
    worker = AsyncMock()
    worker.base_url = "http://mock-comfy:8188"
    if online:
        worker.system_stats = AsyncMock(return_value=_fake_stats(name=name, free=free))
    else:
        worker.system_stats = AsyncMock(side_effect=RuntimeError("connection refused"))
    worker.free = AsyncMock(return_value=None)
    worker.run = AsyncMock(return_value=b"png")
    return worker


class ParseGpuWorkersTest(unittest.TestCase):
    def test_parses_multi_worker_env_and_default_gpu(self):
        workers, default_id = qwen_main._parse_gpu_workers(
            workers_env="1=http://comfyui:8188,2=http://comfyui-gpu2:8188",
            default_env="2",
            fallback_url="http://127.0.0.1:8188",
        )
        self.assertEqual(list(workers.keys()), ["1", "2"])
        self.assertEqual(workers["1"].base_url, "http://comfyui:8188")
        self.assertEqual(workers["2"].base_url, "http://comfyui-gpu2:8188")
        self.assertEqual(default_id, "2")

    def test_falls_back_to_single_worker_when_env_empty(self):
        workers, default_id = qwen_main._parse_gpu_workers(
            workers_env="",
            default_env="",
            fallback_url="http://comfyui:8188",
        )
        self.assertEqual(list(workers.keys()), ["1"])
        self.assertEqual(workers["1"].base_url, "http://comfyui:8188")
        self.assertEqual(default_id, "1")

    def test_falls_back_to_first_worker_if_default_not_in_map(self):
        workers, default_id = qwen_main._parse_gpu_workers(
            workers_env="1=http://comfyui:8188,2=http://comfyui-gpu2:8188",
            default_env="9",
            fallback_url="http://127.0.0.1:8188",
        )
        self.assertEqual(default_id, "1")


class GpuNodeRoutingTest(unittest.TestCase):
    def setUp(self):
        self.w1 = _make_worker(name="cuda:0 NVIDIA GeForce RTX 5080 : cudaMallocAsync", free=15 * 1024**3)
        self.w2 = _make_worker(name="cuda:0 NVIDIA GeForce RTX 5080 : cudaMallocAsync", free=14 * 1024**3)
        self._orig_workers = qwen_main.workers
        self._orig_default = qwen_main.DEFAULT_GPU_ID
        self._orig_active = qwen_main.active_gpu_id
        self._orig_comfy = qwen_main.comfy
        self._orig_unloaded = qwen_main.is_unloaded
        self._orig_loading = qwen_main.is_loading

        qwen_main.workers = {"1": self.w1, "2": self.w2}
        qwen_main.DEFAULT_GPU_ID = "2"
        qwen_main.active_gpu_id = "2"
        qwen_main.comfy = self.w2
        qwen_main.is_unloaded = True
        qwen_main.is_loading = False
        self.client = TestClient(qwen_main.app)

    def tearDown(self):
        qwen_main.workers = self._orig_workers
        qwen_main.DEFAULT_GPU_ID = self._orig_default
        qwen_main.active_gpu_id = self._orig_active
        qwen_main.comfy = self._orig_comfy
        qwen_main.is_unloaded = self._orig_unloaded
        qwen_main.is_loading = self._orig_loading

    def test_list_gpus_reports_online_stats_and_active_flag(self):
        self.w1 = _make_worker(online=False)
        qwen_main.workers["1"] = self.w1
        qwen_main.is_unloaded = False

        resp = self.client.get("/v1/system/gpus")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["active_gpu"], "2")
        self.assertEqual(data["default_gpu"], "2")
        gpus = {item["id"]: item for item in data["gpus"]}
        self.assertFalse(gpus["1"]["online"])
        self.assertFalse(gpus["1"]["active"])
        self.assertFalse(gpus["1"]["loaded"])

        self.assertTrue(gpus["2"]["online"])
        self.assertTrue(gpus["2"]["active"])
        self.assertTrue(gpus["2"]["loaded"])
        self.assertTrue(gpus["2"]["default"])
        self.assertEqual(gpus["2"]["name"], "NVIDIA GeForce RTX 5080")
        self.assertEqual(gpus["2"]["vram_total_mb"], 16384)
        self.assertEqual(gpus["2"]["vram_free_mb"], 14336)

    def test_load_without_body_uses_active_default_gpu(self):
        resp = self.client.post("/v1/system/load")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ready", "gpu": "2"})
        self.w2.run.assert_awaited_once()
        self.w1.run.assert_not_awaited()

    def test_switch_gpu_frees_previous_and_loads_target(self):
        qwen_main.is_unloaded = False  # currently loaded on GPU 2

        resp = self.client.post("/v1/system/load", json={"gpu_id": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ready", "gpu": "1"})
        self.assertEqual(qwen_main.active_gpu_id, "1")
        self.assertIs(qwen_main.comfy, self.w1)
        self.w2.free.assert_awaited_once_with(unload_models=True, free_memory=True)
        self.w1.run.assert_awaited_once()

    def test_unknown_gpu_returns_400_without_unloading(self):
        qwen_main.is_unloaded = False
        resp = self.client.post("/v1/system/load", json={"gpu_id": "99"})
        self.assertEqual(resp.status_code, 400)
        self.w2.free.assert_not_awaited()
        self.assertEqual(qwen_main.active_gpu_id, "2")

    def test_switch_while_inference_locked_returns_409(self):
        qwen_main.is_unloaded = False

        async def run_test():
            await qwen_main._inference_lock.acquire()
            try:
                resp = self.client.post("/v1/system/load", json={"gpu_id": "1"})
                self.assertEqual(resp.status_code, 409)
                self.assertEqual(qwen_main.active_gpu_id, "2")
                self.w2.free.assert_not_awaited()
            finally:
                qwen_main._inference_lock.release()

        asyncio.run(run_test())

    def test_switch_to_offline_gpu_returns_502_and_preserves_current_gpu(self):
        qwen_main.is_unloaded = False
        qwen_main.workers["1"] = _make_worker(online=False)

        resp = self.client.post("/v1/system/load", json={"gpu_id": "1"})
        self.assertEqual(resp.status_code, 502)
        self.w2.free.assert_not_awaited()
        self.assertEqual(qwen_main.active_gpu_id, "2")
        self.assertFalse(qwen_main.is_unloaded)

    def test_health_and_load_state_include_gpu_id(self):
        health = self.client.get("/health").json()
        self.assertEqual(health["gpu"], "2")
        state = self.client.get("/v1/system/load/state").json()
        self.assertEqual(state["gpu"], "2")


if __name__ == "__main__":
    unittest.main()
