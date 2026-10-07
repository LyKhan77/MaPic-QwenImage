"""Test endpoint service MaPic (`POST /api/service/generate`) untuk Inkspire.

Semua test memakai mock downstream (`generate_image_bytes`) — tanpa GPU, token
asli, atau koneksi Supabase. Test disusun mengikuti pola `test_remove_background.py`:
satu `TestClient` bersama supaya `_generation_lock` level modul tetap terikat ke
satu event loop, plus `unittest.mock.patch` untuk dependency dan storage.
"""

import asyncio
import base64
import threading
import time
import unittest
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from backend import auth as backend_auth
from backend import main
from backend.auth import require_user
from backend.services import supabase_service
from backend.services.qwen_image_service import QwenImageError, QwenImageTimeoutError
from backend.services.supabase_service import GenerationNotFound

SERVICE_PATH = "/api/service/generate"
SERVICE_TOKEN = "unit-test-service-token-bukan-rahasia"
USER_PATH = "/api/generate"


def _png_bytes(size=(8, 8), color=(200, 30, 30)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _encoded(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _body(**extra) -> dict:
    return {"prompt": "Minimal green ink illustration of a creative workspace", **extra}


def _noise_png(min_bytes: int) -> bytes:
    """PNG incompressible yang pasti lebih besar dari `min_bytes`."""
    import os

    side = 1024
    noise = os.urandom(side * side * 3)
    buffer = BytesIO()
    Image.frombytes("RGB", (side, side), noise).save(buffer, format="PNG")
    data = buffer.getvalue()
    assert len(data) > min_bytes, "noise PNG terlalu kecil untuk test ini"
    return data


PNG = _png_bytes()

_CLIENT: TestClient | None = None


def setUpModule():
    # Satu TestClient bersama menjaga semua request di event loop yang sama;
    # `_generation_lock` level modul akan terikat ke loop pertama yang memakainya.
    global _CLIENT
    _CLIENT = TestClient(main.app)
    _CLIENT.__enter__()


def tearDownModule():
    assert _CLIENT is not None
    _CLIENT.__exit__(None, None, None)


class ServiceApiTestCase(unittest.TestCase):
    def setUp(self):
        self.client = _CLIENT
        self.user_id = uuid4()
        main._active_generations.clear()
        self.addCleanup(main._active_generations.clear)
        self.addCleanup(main.app.dependency_overrides.clear)

    def _enable_service(self, token: str = SERVICE_TOKEN) -> str:
        patcher = patch.object(backend_auth, "MAPIC_SERVICE_TOKEN", token)
        patcher.start()
        self.addCleanup(patcher.stop)
        return token

    def _authenticate_user(self) -> None:
        main.app.dependency_overrides[require_user] = lambda: self.user_id

    def _mock_inference(self, side_effect=None, return_value=None) -> AsyncMock:
        if side_effect is not None:
            mock = AsyncMock(side_effect=side_effect)
        else:
            mock = AsyncMock(return_value=return_value if return_value is not None else PNG)
        patcher = patch.object(main, "generate_image_bytes", mock)
        patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _post(self, payload: dict, headers: dict | None = None, token: str = SERVICE_TOKEN):
        request_headers = dict(headers or {})
        request_headers.setdefault("Authorization", f"Bearer {token}")
        return self.client.post(SERVICE_PATH, json=payload, headers=request_headers)

    def _fill_queue(self):
        """Isi antrean gabungan sampai penuh dengan campuran job pengguna/service."""
        for index in range(main.MAX_GLOBAL_GENERATIONS):
            if index % 2:
                main._active_generations[f"user-{index}"] = {
                    "user_id": str(uuid4()),
                    "prompt": "p",
                    "queued_at": time.time(),
                    "started_at": None,
                    "status": "queued",
                    "num_inference_steps": 40,
                    "num_ref_images": 0,
                    "resolution": 1024,
                    "cfg_enabled": False,
                }
            else:
                main._active_generations[f"service-{index}"] = {
                    "kind": "service",
                    "queued_at": time.time(),
                    "started_at": None,
                    "status": "queued",
                }


class ServiceDisabledTest(ServiceApiTestCase):
    def test_missing_env_token_fails_closed_with_503(self):
        self._enable_service("")

        self.assertEqual(self._post(_body()).status_code, 503)
        self.assertEqual(self._post(_body(), token="whatever").status_code, 503)

    def test_whitespace_only_env_token_also_fails_closed(self):
        # `.env` yang salah edit (hanya spasi/newline) harus tetap 503, bukan
        # route aktif dengan token yang tidak mungkin cocok.
        self._enable_service("   \n\t ")

        self.assertEqual(self._post(_body()).status_code, 503)

    def test_user_routes_keep_working_while_service_is_disabled(self):
        self._enable_service("")
        self._authenticate_user()
        inference = self._mock_inference()
        upload = Mock(return_value=("user/path.png", "https://example.supabase.co/user/path.png"))
        insert = Mock(return_value={
            "id": str(uuid4()),
            "user_id": str(self.user_id),
            "prompt": "x",
            "image_path": "user/path.png",
            "public_url": "https://example.supabase.co/user/path.png",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        with patch.object(main, "upload_image", upload), patch.object(main, "insert_generation", insert):
            response = self.client.post(USER_PATH, json={"prompt": "x"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(inference.call_count, 1)
        self.assertEqual(self.client.get("/api/generations/active").status_code, 200)


class ServiceAuthTest(ServiceApiTestCase):
    def setUp(self):
        super().setUp()
        self._enable_service()
        self.inference = self._mock_inference()

    def test_missing_header_is_401(self):
        response = self.client.post(SERVICE_PATH, json=_body())

        self.assertEqual(response.status_code, 401)
        self.inference.assert_not_called()

    def test_non_bearer_scheme_is_401(self):
        response = self.client.post(
            SERVICE_PATH, json=_body(), headers={"Authorization": "Basic abc123"}
        )

        self.assertEqual(response.status_code, 401)
        self.inference.assert_not_called()

    def test_wrong_token_is_401_before_inference(self):
        for token in ("wrong", SERVICE_TOKEN + "x", SERVICE_TOKEN[:-1], SERVICE_TOKEN.upper()):
            with self.subTest(token=token):
                self.assertEqual(self._post(_body(), token=token).status_code, 401)

        self.inference.assert_not_called()

    def test_env_token_with_surrounding_whitespace_still_matches(self):
        self._enable_service("  secret-token  ")

        response = self._post(_body(), token="secret-token")

        self.assertEqual(response.status_code, 200)

    def test_service_token_cannot_access_user_endpoints(self):
        # Token service bukan JWT, jadi ditolak sebelum JWKS di-fetch. `fetch_data`
        # di-mock sebagai guard: test tetap offline sekaligus membuktikan tidak ada
        # panggilan jaringan ke Supabase.
        fetch = Mock()
        headers = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
        with patch.object(backend_auth.JWKS, "fetch_data", fetch):
            history = self.client.get(f"/api/history/{uuid4()}", headers=headers)
            delete = self.client.delete(f"/api/history/{uuid4()}", headers=headers)
            generate = self.client.post(USER_PATH, json={"prompt": "x"}, headers=headers)
            active = self.client.get("/api/generations/active", headers=headers)

        for response in (history, delete, generate, active):
            self.assertEqual(response.status_code, 401)
        self.assertEqual(fetch.call_count, 0)
        self.inference.assert_not_called()


class ServiceGenerateSuccessTest(ServiceApiTestCase):
    def setUp(self):
        super().setUp()
        self._enable_service()
        self.inference = self._mock_inference()

    def test_t2i_returns_png_base64_and_minimal_shape(self):
        response = self._post(_body(
            negative_prompt="",
            true_cfg_scale=1.0,
            num_inference_steps=40,
            resolution=1024,
        ))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(list(payload.keys()), ["data"])
        self.assertEqual(list(payload["data"][0].keys()), ["b64_json"])
        self.assertEqual(base64.b64decode(payload["data"][0]["b64_json"]), PNG)

        args = self.inference.call_args.args
        self.assertEqual(args[0], "Minimal green ink illustration of a creative workspace")
        self.assertIsNone(args[1])  # tanpa images = T2I
        self.assertEqual(args[2], 40)
        self.assertEqual(args[3], 1.0)
        self.assertEqual(args[4], "")
        self.assertEqual(args[5], 1024)

    def test_empty_images_list_is_t2i(self):
        response = self._post(_body(images=[]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.inference.call_args.args[1], [])

    def test_i2i_forwards_reference_images_and_returns_png(self):
        reference = _encoded(PNG)
        response = self._post(_body(
            prompt="Turn this sketch into a clean product illustration",
            images=[reference],
            num_inference_steps=40,
            resolution=1024,
        ))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(base64.b64decode(response.json()["data"][0]["b64_json"]), PNG)
        self.assertEqual(self.inference.call_args.args[1], [reference])

    def test_ten_reference_images_are_accepted(self):
        images = [_encoded(PNG) for _ in range(10)]

        response = self._post(_body(images=images))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.inference.call_args.args[1]), 10)

    def test_prompt_of_exactly_2000_chars_is_accepted(self):
        response = self._post(_body(prompt="p" * 2000))

        self.assertEqual(response.status_code, 200)

    def test_success_path_never_touches_supabase(self):
        upload = Mock()
        insert = Mock()
        fetch = Mock()
        delete = Mock()
        delete_image = Mock()
        client_sentinel = Mock()
        jwks = Mock()
        with patch.object(main, "upload_image", upload), patch.object(main, "insert_generation", insert), patch.object(
            main, "fetch_history", fetch
        ), patch.object(main, "delete_generation", delete), patch.object(
            main, "delete_stored_image", delete_image
        ), patch.object(supabase_service, "supabase", client_sentinel), patch.object(
            backend_auth.JWKS, "fetch_data", jwks
        ):
            response = self._post(_body(images=[_encoded(PNG)]))

        self.assertEqual(response.status_code, 200)
        for mocked in (upload, insert, fetch, delete, delete_image):
            mocked.assert_not_called()
        # Sentinel: akses atribut apa pun ke klien Supabase akan tercatat di sini.
        self.assertEqual(client_sentinel.mock_calls, [])
        self.assertEqual(jwks.call_count, 0)


class ServiceValidationTest(ServiceApiTestCase):
    def setUp(self):
        super().setUp()
        self._enable_service()
        self.inference = self._mock_inference()

    def _assert_rejected(self, payload: dict, status: int):
        self.inference.reset_mock()
        response = self._post(payload)

        self.assertEqual(response.status_code, status, response.text)
        self.inference.assert_not_called()

    def test_prompt_is_required_and_not_blank_after_trim(self):
        self._assert_rejected({}, 422)
        self._assert_rejected({"prompt": ""}, 422)
        self._assert_rejected({"prompt": "   \t\n "}, 422)
        self._assert_rejected({"prompt": "x" * 2001}, 422)

    def test_steps_and_cfg_bounds(self):
        self._assert_rejected(_body(num_inference_steps=19), 422)
        self._assert_rejected(_body(num_inference_steps=76), 422)
        self._assert_rejected(_body(true_cfg_scale=0.9), 422)
        self._assert_rejected(_body(true_cfg_scale=3.1), 422)
        self._assert_rejected(_body(true_cfg_scale="high"), 422)

    def test_unsupported_resolution_is_rejected_before_inference(self):
        # Batas host di-pin agar test tidak bergantung env QWEN_MAX_RESOLUTION.
        with patch.object(main, "QWEN_MAX_RESOLUTION", 1024):
            # Literal skema hanya menerima 1024/2048; di atas batas host ditolak 422.
            self._assert_rejected(_body(resolution=512), 422)
            self._assert_rejected(_body(resolution=2048), 422)

    def test_resolution_at_a_raised_host_limit_is_accepted(self):
        with patch.object(main, "QWEN_MAX_RESOLUTION", 2048):
            response = self._post(_body(resolution=2048))

        self.assertEqual(response.status_code, 200)

    def test_more_than_ten_reference_images_is_rejected(self):
        self._assert_rejected(_body(images=[_encoded(PNG) for _ in range(11)]), 422)

    def test_broken_base64_is_rejected(self):
        self._assert_rejected(_body(images=["!!!not-base64!!!"]), 422)

    def test_oversized_base64_string_is_413(self):
        self._assert_rejected(_body(images=["A" * (main.MAX_SERVICE_IMAGE_BASE64_CHARS + 1)]), 413)

    def test_oversized_decoded_image_is_413(self):
        # 2.099.000 byte: di bawah batas karakter base64 (2.800.000) tetapi di atas
        # batas byte hasil decode (2 MiB), jadi yang diuji benar-benar gerbang byte.
        encoded = _encoded(b"\x00" * 2_099_000)
        self.assertLessEqual(len(encoded), main.MAX_SERVICE_IMAGE_BASE64_CHARS)

        self._assert_rejected(_body(images=[encoded]), 413)

    def test_large_real_png_is_rejected_by_the_base64_char_cap(self):
        # PNG noise ~3 MB → base64 ~4,2 juta karakter: ditolak di gerbang karakter,
        # sebelum decode. Gerbang byte hasil decode diuji terpisah di bawah.
        large = _noise_png(main.MAX_SERVICE_IMAGE_BYTES)
        self.assertGreater(len(_encoded(large)), main.MAX_SERVICE_IMAGE_BASE64_CHARS)

        self._assert_rejected(_body(images=[_encoded(large)]), 413)

    def test_image_dimensions_are_bounded(self):
        buffer = BytesIO()
        Image.new("RGB", (2049, 4), (0, 0, 0)).save(buffer, format="PNG")
        self._assert_rejected(_body(images=[_encoded(buffer.getvalue())]), 422)

    def test_image_at_the_size_cap_is_accepted(self):
        buffer = BytesIO()
        Image.new("RGB", (2048, 2048), (10, 200, 10)).save(buffer, format="PNG")
        response = self._post(_body(images=[_encoded(buffer.getvalue())]))

        self.assertEqual(response.status_code, 200)

    def test_non_png_jpeg_and_unreadable_images_are_rejected(self):
        gif = BytesIO()
        Image.new("RGB", (8, 8)).save(gif, format="GIF")
        self._assert_rejected(_body(images=[_encoded(gif.getvalue())]), 422)
        self._assert_rejected(_body(images=[_encoded(PNG[: len(PNG) // 2])]), 422)
        self._assert_rejected(_body(images=[""]), 422)

    def test_request_body_over_limit_is_413(self):
        patcher = patch.object(main, "MAX_SERVICE_REQUEST_BYTES", 1024)
        patcher.start()
        self.addCleanup(patcher.stop)

        self._assert_rejected(_body(prompt="x" * 2000), 413)

    def test_chunked_body_without_content_length_is_capped(self):
        # Body iterator tidak membawa Content-Length; batas harus tetap berlaku
        # karena hitungan byte dilakukan saat streaming.
        patcher = patch.object(main, "MAX_SERVICE_REQUEST_BYTES", 1024)
        patcher.start()
        self.addCleanup(patcher.stop)

        def chunks():
            yield b'{"prompt": "'
            yield b"x" * 2000
            yield b'"}'

        response = self.client.post(
            SERVICE_PATH,
            content=chunks(),
            headers={"Authorization": f"Bearer {SERVICE_TOKEN}", "Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 413)
        self.inference.assert_not_called()

    def test_chunked_body_under_the_cap_is_accepted(self):
        patcher = patch.object(main, "MAX_SERVICE_REQUEST_BYTES", 4096)
        patcher.start()
        self.addCleanup(patcher.stop)

        def chunks():
            yield b'{"prompt": "chunked'
            yield b' prompt"}'

        response = self.client.post(
            SERVICE_PATH,
            content=chunks(),
            headers={"Authorization": f"Bearer {SERVICE_TOKEN}", "Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.inference.call_count, 1)

    def test_validation_error_shape_matches_fastapi_without_echoing_input(self):
        for payload in ({"images": []}, _body(prompt="", images=[_encoded(PNG)] * 11)):
            with self.subTest(payload=payload):
                self.inference.reset_mock()
                response = self._post(payload)

                self.assertEqual(response.status_code, 422)
                self.assertTrue(response.json()["detail"])
                for error in response.json()["detail"]:
                    self.assertEqual(set(error.keys()), {"type", "loc", "msg"})
                    self.assertEqual(error["loc"][0], "body")
                # Payload base64 yang ditolak tidak boleh digemakan di respons.
                self.assertNotIn(_encoded(PNG), response.text)
                self.inference.assert_not_called()

    def test_auth_is_checked_before_the_body_is_read(self):
        patcher = patch.object(main, "MAX_SERVICE_REQUEST_BYTES", 1024)
        patcher.start()
        self.addCleanup(patcher.stop)

        response = self.client.post(SERVICE_PATH, json=_body(prompt="x" * 2000))

        self.assertEqual(response.status_code, 401)
        self.inference.assert_not_called()


class ServiceAdmissionTest(ServiceApiTestCase):
    def test_user_and_service_share_one_admission_limit(self):
        self._enable_service()
        self._authenticate_user()
        self.inference = self._mock_inference()
        self._fill_queue()

        service_full = self._post(_body())
        user_full = self.client.post(USER_PATH, json={"prompt": "x"})

        self.assertEqual(service_full.status_code, 429)
        self.assertEqual(user_full.status_code, 429)
        self.inference.assert_not_called()

    def test_released_slot_lets_the_next_service_job_run(self):
        self._enable_service()
        self.inference = self._mock_inference()
        self._fill_queue()

        self.assertEqual(self._post(_body()).status_code, 429)

        main._active_generations.pop("service-0")
        self.assertEqual(self._post(_body()).status_code, 200)
        self.assertEqual(self.inference.call_count, 1)

    def test_invalid_request_is_rejected_before_admission(self):
        # Antrean penuh: request yang jelas salah harus tetap 422 (validasi lebih
        # dulu), bukan 429 — supaya klien memperbaiki input, bukan menunggu antrean.
        self._enable_service()
        self.inference = self._mock_inference()
        self._fill_queue()

        with patch.object(main, "QWEN_MAX_RESOLUTION", 1024):
            self.assertEqual(self._post(_body(images=["!!!"])).status_code, 422)
            self.assertEqual(self._post(_body(resolution=2048)).status_code, 422)
        self.assertEqual(self._post(_body()).status_code, 429)
        self.inference.assert_not_called()

    def test_service_jobs_are_hidden_from_the_active_list(self):
        self._authenticate_user()
        self._fill_queue()

        response = self.client.get("/api/generations/active")

        self.assertEqual(response.status_code, 200)
        entries = response.json()
        self.assertEqual(len(entries), main.MAX_GLOBAL_GENERATIONS // 2)
        self.assertTrue(all(entry["id"].startswith("user-") for entry in entries))


class ServiceSharedLockTest(ServiceApiTestCase):
    def test_user_and_service_requests_share_one_inference_lock(self):
        self._enable_service()
        self._authenticate_user()
        state = {"active": 0, "max": 0, "calls": 0}
        entered = threading.Event()
        release = threading.Event()
        results: dict = {}

        async def blocking_inference(*args, **kwargs):
            state["calls"] += 1
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
            entered.set()
            await asyncio.to_thread(release.wait, 10)
            state["active"] -= 1
            return PNG

        upload = Mock(return_value=("user/path.png", "https://example.supabase.co/user/path.png"))
        insert = Mock(return_value={
            "id": str(uuid4()),
            "user_id": str(self.user_id),
            "prompt": "x",
            "image_path": "user/path.png",
            "public_url": "https://example.supabase.co/user/path.png",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        def service_request():
            try:
                results["service"] = self._post(_body())
            except BaseException as exc:  # surfaced as an assertion below
                results["service_error"] = exc

        def user_request():
            try:
                results["user"] = self.client.post(USER_PATH, json={"prompt": "x"})
            except BaseException as exc:  # surfaced as an assertion below
                results["user_error"] = exc

        with patch.object(main, "generate_image_bytes", blocking_inference), patch.object(
            main, "upload_image", upload
        ), patch.object(main, "insert_generation", insert):
            service_thread = threading.Thread(target=service_request)
            user_thread = threading.Thread(target=user_request)
            service_thread.start()
            try:
                self.assertTrue(entered.wait(10), "inference never started")

                # Metadata job service sementara tidak memuat prompt/identitas.
                service_entry = next(
                    info for info in main._active_generations.values() if info.get("kind") == "service"
                )
                self.assertEqual(set(service_entry.keys()), {"kind", "queued_at", "started_at", "status"})

                user_thread.start()
                deadline = time.time() + 5
                while time.time() < deadline and len(main._active_generations) < 2:
                    time.sleep(0.01)
                self.assertEqual(len(main._active_generations), 2, "request kedua tidak sampai ke antrean")
                # Kalau lock tidak dipakai bersama, request kedua sudah menaikkan nilai ini.
                self.assertEqual(state["max"], 1)
            finally:
                release.set()
                service_thread.join(10)
                user_thread.join(10)

        self.assertFalse(service_thread.is_alive())
        self.assertFalse(user_thread.is_alive())
        self.assertNotIn("service_error", results)
        self.assertNotIn("user_error", results)
        self.assertEqual(results["service"].status_code, 200)
        self.assertEqual(results["user"].status_code, 200)
        self.assertEqual(state["max"], 1)
        self.assertEqual(state["calls"], 2)
        self.assertEqual(main._active_generations, {})


class ServiceCancellationTest(ServiceApiTestCase):
    def test_cancelled_request_releases_the_slot_and_lock(self):
        # Pembatalan request (mis. shutdown) harus melewatkan `finally` yang sama:
        # slot antrean dan lock tidak boleh tertinggal terpakai.
        self._enable_service()
        release = asyncio.Event()
        entered = asyncio.Event()

        async def blocking_inference(*args, **kwargs):
            entered.set()
            await release.wait()
            return PNG

        # Lock baru per test: `asyncio.run` memakai event loop sendiri.
        fresh_lock = asyncio.Lock()
        lock_patch = patch.object(main, "_generation_lock", fresh_lock)
        lock_patch.start()
        self.addCleanup(lock_patch.stop)
        inference_patch = patch.object(main, "generate_image_bytes", blocking_inference)
        inference_patch.start()
        self.addCleanup(inference_patch.stop)

        async def scenario():
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                task = asyncio.create_task(client.post(
                    SERVICE_PATH,
                    json=_body(),
                    headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
                ))
                await asyncio.wait_for(entered.wait(), 5)
                self.assertEqual(len(main._active_generations), 1)

                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task

        asyncio.run(scenario())

        self.assertEqual(main._active_generations, {})
        self.assertFalse(fresh_lock.locked())


class ServiceDownstreamErrorTest(ServiceApiTestCase):
    def setUp(self):
        super().setUp()
        self._enable_service()

    def test_timeout_is_504_and_slot_is_released(self):
        self._mock_inference(side_effect=QwenImageTimeoutError("Qwen-Image server timed out"))

        response = self._post(_body())

        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["detail"], "Generation timed out")
        self.assertEqual(main._active_generations, {})

    def test_downstream_failure_is_502_without_leaking_internals(self):
        self._mock_inference(side_effect=QwenImageError("Resolution 2048 exceeds this server's limit of 1024"))

        response = self._post(_body())

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Generation failed")
        self.assertNotIn("1024", response.text)
        self.assertEqual(main._active_generations, {})

    def test_invalid_downstream_result_is_502(self):
        self._mock_inference(side_effect=QwenImageError("Respons Qwen-Image tidak berisi gambar"))

        self.assertEqual(self._post(_body()).status_code, 502)

    def test_slot_is_reusable_after_failure(self):
        self._mock_inference(side_effect=[QwenImageError("boom"), PNG])

        self.assertEqual(self._post(_body()).status_code, 502)
        self.assertEqual(main._active_generations, {})
        self.assertEqual(self._post(_body()).status_code, 200)
        self.assertEqual(main._active_generations, {})


class UserAuthRegressionTest(ServiceApiTestCase):
    def test_user_generate_still_requires_auth(self):
        jwks = Mock()
        with patch.object(backend_auth.JWKS, "get_signing_key_from_jwt", jwks):
            response = self.client.post(USER_PATH, json={"prompt": "x"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(jwks.call_count, 0)

    def test_history_of_another_user_is_403(self):
        self._authenticate_user()

        response = self.client.get(f"/api/history/{uuid4()}")

        self.assertEqual(response.status_code, 403)

    def test_history_uses_the_token_identity(self):
        self._authenticate_user()
        with patch.object(main, "fetch_history", return_value=[]) as fetch:
            response = self.client.get(f"/api/history/{self.user_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(fetch.call_args.args, (self.user_id,))

    def test_delete_is_scoped_to_the_token_owner(self):
        self._authenticate_user()
        record_id = uuid4()
        with patch.object(main, "delete_generation", side_effect=GenerationNotFound("not found")) as delete:
            response = self.client.delete(f"/api/history/{record_id}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(delete.call_args.args, (record_id, self.user_id))


if __name__ == "__main__":
    unittest.main()
