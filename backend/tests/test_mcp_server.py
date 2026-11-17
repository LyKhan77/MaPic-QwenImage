"""Test endpoint service cutout (`POST /api/service/remove-background`) dan MCP Streamable HTTP (`POST /mcp`)."""

import base64
import unittest
from io import BytesIO
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient
from PIL import Image

from backend import main
from backend.services import remove_background_service, supabase_service
from backend.services.qwen_image_service import QwenImageError

SERVICE_TOKEN = "unit-test-mcp-token-bukan-rahasia"
CUTOUT_SERVICE_PATH = "/api/service/remove-background"
MCP_PATH = "/mcp"


def _png_bytes(size=(16, 16), color=(20, 120, 220), mode="RGB") -> bytes:
    buf = BytesIO()
    Image.new(mode, size, color).save(buf, format="PNG")
    return buf.getvalue()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


PNG_BYTES = _png_bytes()
PNG_RGBA_BYTES = _png_bytes(color=(20, 120, 220, 0), mode="RGBA")


def _headers(token: str = SERVICE_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class ServiceRemoveBackgroundTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_disabled_when_service_token_missing(self):
        with patch("backend.auth.MAPIC_SERVICE_TOKEN", ""):
            resp = self.client.post(CUTOUT_SERVICE_PATH, headers=_headers(), json={"image": _b64(PNG_BYTES)})
        self.assertEqual(resp.status_code, 503)

    def test_missing_or_wrong_token_is_401(self):
        with patch("backend.auth.MAPIC_SERVICE_TOKEN", SERVICE_TOKEN):
            self.assertEqual(self.client.post(CUTOUT_SERVICE_PATH, json={"image": _b64(PNG_BYTES)}).status_code, 401)
            self.assertEqual(
                self.client.post(CUTOUT_SERVICE_PATH, headers=_headers("wrong"), json={"image": _b64(PNG_BYTES)}).status_code,
                401,
            )

    def test_success_returns_png_without_touching_supabase(self):
        with (
            patch("backend.auth.MAPIC_SERVICE_TOKEN", SERVICE_TOKEN),
            patch.object(remove_background_service, "remove_background_png", return_value=PNG_RGBA_BYTES) as mock_cutout,
            patch.object(supabase_service, "upload_image", side_effect=AssertionError("must not upload")),
            patch.object(supabase_service, "insert_generation", side_effect=AssertionError("must not insert")),
        ):
            resp = self.client.post(CUTOUT_SERVICE_PATH, headers=_headers(), json={"image": _b64(PNG_BYTES)})

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(base64.b64decode(body["data"][0]["b64_json"]), PNG_RGBA_BYTES)
        mock_cutout.assert_called_once()

    def test_invalid_base64_is_422_without_echoing_input(self):
        with patch("backend.auth.MAPIC_SERVICE_TOKEN", SERVICE_TOKEN):
            resp = self.client.post(CUTOUT_SERVICE_PATH, headers=_headers(), json={"image": "not-base64!!!"})
        self.assertEqual(resp.status_code, 422)

    def test_busy_cutout_lock_is_429(self):
        async def run_check():
            await main._remove_background_lock.acquire()
            try:
                with patch("backend.auth.MAPIC_SERVICE_TOKEN", SERVICE_TOKEN):
                    resp = self.client.post(CUTOUT_SERVICE_PATH, headers=_headers(), json={"image": _b64(PNG_BYTES)})
                self.assertEqual(resp.status_code, 429)
            finally:
                main._remove_background_lock.release()

        import asyncio
        asyncio.run(run_check())


class McpEndpointTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_mcp_requires_service_token_and_fails_closed(self):
        rpc = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        with patch("backend.auth.MAPIC_SERVICE_TOKEN", ""):
            self.assertEqual(self.client.post(MCP_PATH, headers=_headers(), json=rpc).status_code, 503)
        with patch("backend.auth.MAPIC_SERVICE_TOKEN", SERVICE_TOKEN):
            self.assertEqual(self.client.post(MCP_PATH, json=rpc).status_code, 401)
            self.assertEqual(self.client.post(MCP_PATH, headers=_headers("bad"), json=rpc).status_code, 401)

    def test_get_mcp_returns_405(self):
        with patch("backend.auth.MAPIC_SERVICE_TOKEN", SERVICE_TOKEN):
            resp = self.client.get(MCP_PATH, headers=_headers())
        self.assertEqual(resp.status_code, 405)

    def test_initialize_notification_ping_and_tools_list(self):
        with patch("backend.auth.MAPIC_SERVICE_TOKEN", SERVICE_TOKEN):
            init_resp = self.client.post(
                MCP_PATH,
                headers=_headers(),
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test"}},
                },
            )
            self.assertEqual(init_resp.status_code, 200)
            init_data = init_resp.json()
            self.assertEqual(init_data["id"], 1)
            self.assertEqual(init_data["result"]["protocolVersion"], "2025-03-26")
            self.assertEqual(init_data["result"]["serverInfo"]["name"], "mapic-mcp")
            self.assertIn("tools", init_data["result"]["capabilities"])

            notif_resp = self.client.post(
                MCP_PATH,
                headers=_headers(),
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            self.assertEqual(notif_resp.status_code, 202)

            ping_resp = self.client.post(
                MCP_PATH,
                headers=_headers(),
                json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
            )
            self.assertEqual(ping_resp.status_code, 200)
            self.assertEqual(ping_resp.json()["result"], {})

            tools_resp = self.client.post(
                MCP_PATH,
                headers=_headers(),
                json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
            )
            self.assertEqual(tools_resp.status_code, 200)
            tools = {tool["name"]: tool for tool in tools_resp.json()["result"]["tools"]}
            self.assertEqual(set(tools.keys()), {"generate_image", "remove_background", "get_model_status"})
            self.assertIn("prompt", tools["generate_image"]["inputSchema"]["properties"])
            self.assertIn("image", tools["remove_background"]["inputSchema"]["properties"])

    def test_call_generate_image_returns_image_content(self):
        with (
            patch("backend.auth.MAPIC_SERVICE_TOKEN", SERVICE_TOKEN),
            patch.object(main, "generate_image_bytes", new=AsyncMock(return_value=PNG_BYTES)) as mock_gen,
            patch.object(supabase_service, "upload_image", side_effect=AssertionError("must not upload")),
            patch.object(supabase_service, "insert_generation", side_effect=AssertionError("must not insert")),
        ):
            resp = self.client.post(
                MCP_PATH,
                headers=_headers(),
                json={
                    "jsonrpc": "2.0",
                    "id": 10,
                    "method": "tools/call",
                    "params": {
                        "name": "generate_image",
                        "arguments": {"prompt": "minimal coffee logo", "num_inference_steps": 30},
                    },
                },
            )
        self.assertEqual(resp.status_code, 200)
        result = resp.json()["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["content"][0]["type"], "image")
        self.assertEqual(result["content"][0]["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(result["content"][0]["data"]), PNG_BYTES)
        self.assertEqual(result["content"][1]["type"], "text")
        mock_gen.assert_awaited_once()

    def test_call_generate_image_error_returns_is_error_true(self):
        with (
            patch("backend.auth.MAPIC_SERVICE_TOKEN", SERVICE_TOKEN),
            patch.object(main, "QWEN_MAX_RESOLUTION", 1024),
            patch.object(main, "generate_image_bytes", new=AsyncMock(side_effect=QwenImageError("boom"))),
        ):
            resp = self.client.post(
                MCP_PATH,
                headers=_headers(),
                json={
                    "jsonrpc": "2.0",
                    "id": 11,
                    "method": "tools/call",
                    "params": {
                        "name": "generate_image",
                        "arguments": {"prompt": "hi", "resolution": 2048},
                    },
                },
            )
        self.assertEqual(resp.status_code, 200)
        result = resp.json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("1024", result["content"][0]["text"])

    def test_call_remove_background_returns_transparent_png(self):
        with (
            patch("backend.auth.MAPIC_SERVICE_TOKEN", SERVICE_TOKEN),
            patch.object(remove_background_service, "remove_background_png", return_value=PNG_RGBA_BYTES),
        ):
            resp = self.client.post(
                MCP_PATH,
                headers=_headers(),
                json={
                    "jsonrpc": "2.0",
                    "id": 12,
                    "method": "tools/call",
                    "params": {
                        "name": "remove_background",
                        "arguments": {"image": _b64(PNG_BYTES)},
                    },
                },
            )
        self.assertEqual(resp.status_code, 200)
        result = resp.json()["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["content"][0]["type"], "image")
        self.assertEqual(base64.b64decode(result["content"][0]["data"]), PNG_RGBA_BYTES)

    def test_call_get_model_status_returns_status_and_gpus(self):
        gpu_payload = {"active_gpu": "2", "default_gpu": "2", "gpus": [{"id": "2", "online": True}]}
        with (
            patch("backend.auth.MAPIC_SERVICE_TOKEN", SERVICE_TOKEN),
            patch.object(main, "get_health_status", new=AsyncMock(return_value="ready")),
            patch.object(main, "get_gpu_nodes", new=AsyncMock(return_value=gpu_payload)),
        ):
            resp = self.client.post(
                MCP_PATH,
                headers=_headers(),
                json={
                    "jsonrpc": "2.0",
                    "id": 13,
                    "method": "tools/call",
                    "params": {"name": "get_model_status", "arguments": {}},
                },
            )
        self.assertEqual(resp.status_code, 200)
        result = resp.json()["result"]
        self.assertFalse(result["isError"])
        self.assertIn('"active_gpu": "2"', result["content"][0]["text"])

    def test_call_unknown_tool_returns_jsonrpc_invalid_params(self):
        with patch("backend.auth.MAPIC_SERVICE_TOKEN", SERVICE_TOKEN):
            resp = self.client.post(
                MCP_PATH,
                headers=_headers(),
                json={
                    "jsonrpc": "2.0",
                    "id": 14,
                    "method": "tools/call",
                    "params": {"name": "does_not_exist", "arguments": {}},
                },
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
