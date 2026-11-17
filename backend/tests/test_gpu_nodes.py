"""Test endpoint GPU node selector di backend (`GET /api/system/gpus`, `POST /api/load`)."""

import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from backend import main
from backend.auth import require_user
from backend.services.qwen_image_service import QwenImageRequestError


class GpuNodeBackendTest(unittest.TestCase):
    def setUp(self):
        self.user_id = uuid4()
        main.app.dependency_overrides[require_user] = lambda: self.user_id
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.clear()

    def test_get_gpus_requires_auth(self):
        main.app.dependency_overrides.clear()
        resp = self.client.get("/api/system/gpus")
        self.assertEqual(resp.status_code, 401)

    def test_get_gpus_forwards_facade_payload(self):
        payload = {
            "active_gpu": "2",
            "default_gpu": "2",
            "gpus": [
                {
                    "id": "1",
                    "name": "NVIDIA GeForce RTX 5080",
                    "vram_total_mb": 16303,
                    "vram_free_mb": 15923,
                    "online": True,
                    "loaded": False,
                    "active": False,
                    "default": False,
                },
                {
                    "id": "2",
                    "name": "NVIDIA GeForce RTX 5080",
                    "vram_total_mb": 16303,
                    "vram_free_mb": 15881,
                    "online": True,
                    "loaded": True,
                    "active": True,
                    "default": True,
                },
            ],
        }
        with patch.object(main, "get_gpu_nodes", new=AsyncMock(return_value=payload)):
            resp = self.client.get("/api/system/gpus")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), payload)

    def test_load_without_body_calls_load_model_with_none(self):
        mock_load = AsyncMock(return_value={"status": "ready", "gpu": "2"})
        with patch.object(main, "load_model", new=mock_load):
            resp = self.client.post("/api/load")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ready", "gpu": "2"})
        mock_load.assert_awaited_once_with(None)

    def test_load_with_gpu_id_forwards_target_gpu(self):
        mock_load = AsyncMock(return_value={"status": "ready", "gpu": "1"})
        with patch.object(main, "load_model", new=mock_load):
            resp = self.client.post("/api/load", json={"gpu_id": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ready", "gpu": "1"})
        mock_load.assert_awaited_once_with("1")

    def test_load_with_blank_gpu_id_is_422(self):
        resp = self.client.post("/api/load", json={"gpu_id": "   "})
        self.assertEqual(resp.status_code, 422)

    def test_load_forwards_409_conflict_from_facade(self):
        err = QwenImageRequestError(409, "Cannot switch or load GPU while a generation is in progress")
        with patch.object(main, "load_model", new=AsyncMock(side_effect=err)):
            resp = self.client.post("/api/load", json={"gpu_id": "1"})
        self.assertEqual(resp.status_code, 409)
        self.assertIn("generation is in progress", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
