import base64
import importlib
import os
import struct
import sys
import tempfile
import threading
import time
import unittest
import zlib
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from backend import main
from backend.auth import require_user
from backend.services import remove_background_service as service
from backend.services.supabase_service import SupabaseError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _encoded(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode()


class RemoveBackgroundTest(unittest.TestCase):
    def setUp(self):
        # Fake local weights so the offline weight check passes without network.
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        model_dir = os.path.join(self.home.name, "models", service.MODEL_NAME)
        os.makedirs(model_dir)
        with open(os.path.join(model_dir, f"{service.MODEL_NAME}.onnx"), "wb") as handle:
            handle.write(b"stub")
        env = patch.dict(os.environ, {"REMBG_HOME": self.home.name})
        env.start()
        self.addCleanup(env.stop)
        # Session cache is module-level: reset for order-independent tests.
        self.addCleanup(setattr, service, "_session", service._session)
        service._session = None

    def test_output_is_rgba_png_with_source_size(self):
        source = Image.new("RGBA", (4, 4), (10, 20, 30, 255))
        model = Image.new("RGBA", (4, 4), (0, 0, 0, 200))

        with patch.object(service, "_session_factory", return_value=object()), patch.object(
            service, "_extract", return_value=_png(model)
        ):
            output = service.remove_background_png(_png(source))

        self.assertTrue(output.startswith(PNG_SIGNATURE))
        with Image.open(BytesIO(output)) as result:
            self.assertEqual(result.mode, "RGBA")
            self.assertEqual(result.size, source.size)
            self.assertEqual(result.getchannel("A").getextrema(), (200, 200))

    def test_rgb_comes_from_source_not_model(self):
        source = Image.new("RGBA", (4, 1))
        colours = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (123, 45, 67, 255)]
        for x, colour in enumerate(colours):
            source.putpixel((x, 0), colour)
        model = Image.new("RGBA", (4, 1), (0, 0, 255, 255))

        with patch.object(service, "_session_factory", return_value=object()), patch.object(
            service, "_extract", return_value=_png(model)
        ):
            output = service.remove_background_png(_png(source))

        with Image.open(BytesIO(output)) as result:
            for x, colour in enumerate(colours):
                self.assertEqual(result.getpixel((x, 0))[:3], colour[:3])

    def test_alpha_is_intersection_of_source_and_model(self):
        source = Image.new("RGBA", (3, 3), (255, 255, 255, 255))
        source.putpixel((0, 0), (255, 255, 255, 0))
        model = Image.new("RGBA", (3, 3), (0, 0, 0, 255))
        model.putpixel((1, 1), (0, 0, 0, 0))
        model.putpixel((2, 2), (0, 0, 0, 120))

        with patch.object(service, "_session_factory", return_value=object()), patch.object(
            service, "_extract", return_value=_png(model)
        ):
            output = service.remove_background_png(_png(source))

        with Image.open(BytesIO(output)) as result:
            self.assertEqual(result.getpixel((0, 0))[3], 0)
            self.assertEqual(result.getpixel((1, 1))[3], 0)
            self.assertEqual(result.getpixel((2, 2))[3], 120)
            self.assertEqual(result.getpixel((0, 1))[3], 255)

    def test_exif_orientation_is_normalised(self):
        # 3x2 stored, shown as 2x3 after orientation 6 (rotate 90 CW). Colours
        # are distinct so a wrong rotation cannot pass on size alone.
        stored = Image.new("RGB", (3, 2))
        for index, colour in enumerate(
            [
                (255, 0, 0),
                (0, 255, 0),
                (0, 0, 255),
                (255, 255, 0),
                (0, 255, 255),
                (255, 0, 255),
            ]
        ):
            stored.putpixel((index % 3, index // 3), colour)
        exif = stored.getexif()
        exif[274] = 6
        buffer = BytesIO()
        stored.save(buffer, format="PNG", exif=exif)
        model = Image.new("RGBA", (2, 3), (0, 0, 0, 255))

        with patch.object(service, "_session_factory", return_value=object()), patch.object(
            service, "_extract", return_value=_png(model)
        ):
            output = service.remove_background_png(buffer.getvalue())

        with Image.open(BytesIO(output)) as result:
            self.assertEqual(result.size, (2, 3))
            # Displayed (x, y) is stored (y, 2 - 1 - x) for a 90 CW rotation.
            self.assertEqual(result.getpixel((0, 0))[:3], (255, 255, 0))
            self.assertEqual(result.getpixel((1, 0))[:3], (255, 0, 0))
            self.assertEqual(result.getpixel((0, 1))[:3], (0, 255, 255))
            self.assertEqual(result.getpixel((1, 1))[:3], (0, 255, 0))
            self.assertEqual(result.getpixel((0, 2))[:3], (255, 0, 255))
            self.assertEqual(result.getpixel((1, 2))[:3], (0, 0, 255))

    def test_import_does_not_load_rembg(self):
        for name in [key for key in sys.modules if key == "rembg" or key.startswith("rembg.")]:
            del sys.modules[name]

        importlib.reload(service)

        self.assertNotIn("rembg", sys.modules)
        self.assertNotIn("rembg.sessions", sys.modules)

    def test_missing_weights_raises_model_unavailable_without_network(self):
        source = _png(Image.new("RGBA", (4, 4), (0, 0, 0, 255)))

        with tempfile.TemporaryDirectory() as empty_home:
            with patch.dict(os.environ, {"REMBG_HOME": empty_home}) as env, patch.object(
                service, "_session_factory", side_effect=AssertionError("session must not be built")
            ):
                env.pop("U2NET_HOME", None)
                env.pop("MODEL_CHECKSUM_DISABLED", None)
                with self.assertRaises(service.ModelUnavailableError) as caught:
                    service.remove_background_png(source)

            # The error names every path that was searched, since legacy_home does
            # not follow REMBG_HOME, only U2NET_HOME. Match the two layouts instead.
            self.assertIn(os.path.join(empty_home, "models"), str(caught.exception))
            self.assertIn(os.path.join(".u2net", f"{service.MODEL_NAME}.onnx"), str(caught.exception))

            # Nothing was downloaded and no offline override was left behind.
            self.assertEqual(os.listdir(empty_home), [])
            self.assertIsNone(os.environ.get("MODEL_CHECKSUM_DISABLED"))

    def test_cutout_without_alpha_is_rejected(self):
        source = Image.new("RGBA", (4, 4), (10, 20, 30, 255))
        opaque_model = Image.new("RGB", (4, 4), (0, 0, 0))

        with patch.object(service, "_session_factory", return_value=object()), patch.object(
            service, "_extract", return_value=_png(opaque_model)
        ):
            with self.assertRaises(service.RemoveBackgroundError) as caught:
                service.remove_background_png(_png(source))

        self.assertIs(type(caught.exception), service.RemoveBackgroundError)
        self.assertIn("alpha", str(caught.exception))

    def test_model_size_mismatch_raises(self):
        source = Image.new("RGBA", (4, 4), (0, 0, 0, 255))
        model = Image.new("RGBA", (3, 3), (0, 0, 0, 255))

        with patch.object(service, "_session_factory", return_value=object()), patch.object(
            service, "_extract", return_value=_png(model)
        ):
            with self.assertRaises(service.RemoveBackgroundError) as caught:
                service.remove_background_png(_png(source))

        self.assertIs(type(caught.exception), service.RemoveBackgroundError)

    def test_session_is_reused_across_calls(self):
        source = _png(Image.new("RGBA", (2, 2), (1, 2, 3, 255)))
        model = _png(Image.new("RGBA", (2, 2), (0, 0, 0, 255)))

        with patch.object(service, "_session_factory", return_value=object()) as factory, patch.object(
            service, "_extract", return_value=model
        ):
            service.remove_background_png(source)
            service.remove_background_png(source)

        self.assertEqual(factory.call_count, 1)

    def test_concurrent_callers_build_one_session(self):
        def slow_factory():
            time.sleep(0.05)
            return object()

        with patch.object(service, "_session_factory", side_effect=slow_factory) as factory:
            threads = [
                threading.Thread(target=service._session_for_model) for _ in range(8)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(factory.call_count, 1)


def _tiny_png() -> bytes:
    return _png(Image.new("RGBA", (2, 2), (10, 20, 30, 255)))


def _zero_size_png() -> bytes:
    """A structurally valid PNG whose IHDR declares 0x0.

    Pillow refuses to open zero-dimension images at all, so this exercises the
    contract's 422 (Pillow cannot open) branch rather than the explicit
    dimension check, which stays as defence for future formats.
    """
    data = bytearray(_png(Image.new("RGB", (1, 1), (1, 2, 3))))
    header = bytes(struct.pack(">II", 0, 0) + data[24:29])
    data[16:29] = header
    struct.pack_into(">I", data, 29, zlib.crc32(b"IHDR" + header) & 0xFFFFFFFF)
    return bytes(data)


_CLIENT: TestClient | None = None


def setUpModule():
    # One shared TestClient keeps every request on the same event loop; the
    # endpoint's module-level asyncio.Lock is loop-bound and a fresh loop per
    # test would trip "bound to a different event loop".
    global _CLIENT
    _CLIENT = TestClient(main.app)
    _CLIENT.__enter__()


def tearDownModule():
    assert _CLIENT is not None
    _CLIENT.__exit__(None, None, None)


class RemoveBackgroundEndpointTest(unittest.TestCase):
    def setUp(self):
        self.client = _CLIENT
        self.user_id = uuid4()
        self.addCleanup(main.app.dependency_overrides.clear)

    def _authenticate(self):
        main.app.dependency_overrides[require_user] = lambda: self.user_id

    def _post(self, image: str, headers: dict | None = None):
        return self.client.post("/api/remove-background", json={"image": image}, headers=headers or {})

    def _successful_storage(self, insert_error: Exception | None = None):
        uploaded = {}

        def fake_upload(user_id, image_bytes):
            uploaded["user_id"] = user_id
            uploaded["bytes"] = image_bytes
            return "user/path.png", "https://example.supabase.co/user/path.png"

        def fake_insert(user_id, prompt, image_path, public_url):
            uploaded["prompt"] = prompt
            return {
                "id": str(uuid4()),
                "user_id": str(user_id),
                "prompt": prompt,
                "image_path": image_path,
                "public_url": public_url,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        return (
            uploaded,
            patch.object(main, "upload_image", side_effect=fake_upload),
            patch.object(main, "insert_generation", side_effect=insert_error or fake_insert),
        )

    def test_missing_bearer_token_is_401(self):
        response = self._post(_encoded(_tiny_png()))

        self.assertEqual(response.status_code, 401)

    def test_bogus_bearer_token_is_401(self):
        response = self._post(_encoded(_tiny_png()), headers={"Authorization": "Bearer bogus"})

        self.assertEqual(response.status_code, 401)

    def test_missing_image_field_is_422(self):
        self._authenticate()
        response = self.client.post("/api/remove-background", json={})

        self.assertEqual(response.status_code, 422)

    def test_oversized_base64_is_413_before_decoding(self):
        self._authenticate()
        # "!" is not valid base64, so a 413 proves the length pre-check ran first.
        response = self._post("!" * 2_800_001)

        self.assertEqual(response.status_code, 413)

    def test_decoded_bytes_over_two_mib_is_413(self):
        self._authenticate()
        oversized = _encoded(b"\x00" * (2 * 1024 * 1024 + 1))
        assert len(oversized) <= 2_800_000

        response = self._post(oversized)

        self.assertEqual(response.status_code, 413)

    def test_invalid_base64_is_422(self):
        self._authenticate()
        response = self._post("not-base64!!!")

        self.assertEqual(response.status_code, 422)

    def test_non_image_payload_is_422(self):
        self._authenticate()
        response = self._post(_encoded(b"hello, definitely not an image"))

        self.assertEqual(response.status_code, 422)

    def test_bmp_source_is_422(self):
        self._authenticate()
        buffer = BytesIO()
        Image.new("RGB", (4, 4), (1, 2, 3)).save(buffer, format="BMP")

        response = self._post(_encoded(buffer.getvalue()))

        self.assertEqual(response.status_code, 422)

    def test_gif_source_is_422(self):
        self._authenticate()
        buffer = BytesIO()
        Image.new("P", (4, 4), 3).save(buffer, format="GIF")

        response = self._post(_encoded(buffer.getvalue()))

        self.assertEqual(response.status_code, 422)

    def test_zero_size_image_is_422(self):
        self._authenticate()
        response = self._post(_encoded(_zero_size_png()))

        self.assertEqual(response.status_code, 422)

    def test_side_over_2048_is_422(self):
        self._authenticate()
        wide = _png(Image.new("RGB", (2049, 1), (1, 2, 3)))

        response = self._post(_encoded(wide))

        self.assertEqual(response.status_code, 422)

    def test_pixels_over_budget_is_422(self):
        self._authenticate()
        # MAX_PIXELS == MAX_SIDE ** 2, so any image over the pixel budget always
        # breaks a side too; this pins the 422 contract for a real over-budget
        # image. The bound itself is exercised by the accepted 2048x2048 case below.
        tall = _png(Image.new("RGB", (2048, 2049), (1, 2, 3)))

        response = self._post(_encoded(tall))

        self.assertEqual(response.status_code, 422)

    def test_image_at_side_and_pixel_limits_is_accepted(self):
        self._authenticate()
        cutout = _png(Image.new("RGBA", (2, 2), (0, 0, 0, 0)))
        _, upload, insert = self._successful_storage()
        source = _encoded(_png(Image.new("RGB", (2048, 2048), (1, 2, 3))))

        with patch.object(service, "remove_background_png", return_value=cutout), upload, insert:
            response = self._post(source)

        self.assertEqual(response.status_code, 200)

    def test_missing_model_is_503_without_leaking_paths(self):
        self._authenticate()
        error = service.ModelUnavailableError(
            "Local weights for isnet-general-use not found; searched: /home/user/.rembg/models"
        )

        with patch.object(main.logger, "exception"), patch.object(
            service, "remove_background_png", side_effect=error
        ):
            response = self._post(_encoded(_tiny_png()))

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("/home/user", response.text)
        self.assertNotIn("isnet-general-use", response.text)

    def test_worker_failure_is_502(self):
        self._authenticate()

        with patch.object(main.logger, "exception"), patch.object(
            service, "remove_background_png", side_effect=service.RemoveBackgroundError("cutout failed")
        ):
            response = self._post(_encoded(_tiny_png()))

        self.assertEqual(response.status_code, 502)

    def test_insert_failure_is_502_and_removes_uploaded_file(self):
        self._authenticate()
        uploaded, upload, insert = self._successful_storage(SupabaseError("insert exploded"))

        with patch.object(main.logger, "exception"), patch.object(
            service, "remove_background_png", return_value=_png(Image.new("RGBA", (2, 2), (0, 0, 0, 0)))
        ), upload, insert, patch.object(main, "delete_stored_image") as cleanup:
            response = self._post(_encoded(_tiny_png()))

        self.assertEqual(response.status_code, 502)
        cleanup.assert_called_once_with("user/path.png")
        self.assertEqual(uploaded["user_id"], self.user_id)

    def test_upload_failure_is_502_and_cleans_nothing(self):
        self._authenticate()

        with patch.object(main.logger, "exception"), patch.object(
            service, "remove_background_png", return_value=_png(Image.new("RGBA", (2, 2), (0, 0, 0, 0)))
        ), patch.object(main, "upload_image", side_effect=SupabaseError("storage exploded")), patch.object(
            main, "delete_stored_image"
        ) as cleanup, patch.object(main, "insert_generation") as insert:
            response = self._post(_encoded(_tiny_png()))

        self.assertEqual(response.status_code, 502)
        cleanup.assert_not_called()
        insert.assert_not_called()

    def test_success_returns_generation_with_cutout_png(self):
        self._authenticate()
        cutout = _png(Image.new("RGBA", (2, 2), (0, 0, 0, 128)))
        uploaded, upload, insert = self._successful_storage()

        with patch.object(
            service, "remove_background_png", return_value=cutout
        ) as worker, upload, insert:
            response = self._post(_encoded(_tiny_png()))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["prompt"], "Remove background")
        self.assertEqual(body["user_id"], str(self.user_id))
        self.assertEqual(body["image_path"], "user/path.png")
        self.assertEqual(sorted(body), ["created_at", "id", "image_path", "prompt", "public_url", "user_id"])
        worker.assert_called_once()
        self.assertEqual(uploaded["user_id"], self.user_id)
        with Image.open(BytesIO(uploaded["bytes"])) as stored:
            self.assertEqual(stored.format, "PNG")
            self.assertEqual(stored.mode, "RGBA")
        self.assertEqual(main._active_generations, {})

    def test_success_ignores_unloaded_qwen_model(self):
        self._authenticate()
        cutout = _png(Image.new("RGBA", (2, 2), (0, 0, 0, 0)))
        _, upload, insert = self._successful_storage()

        with patch.object(main, "generate_image_bytes", side_effect=AssertionError("Qwen path used")), patch.object(
            main, "get_health_status", return_value="unloaded"
        ), patch.object(service, "remove_background_png", return_value=cutout), upload, insert:
            response = self._post(_encoded(_tiny_png()))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["prompt"], "Remove background")

    def test_success_leaves_qwen_generation_lock_free(self):
        self._authenticate()
        cutout = _png(Image.new("RGBA", (2, 2), (0, 0, 0, 0)))
        _, upload, insert = self._successful_storage()

        with patch.object(service, "remove_background_png", return_value=cutout), upload, insert:
            response = self._post(_encoded(_tiny_png()))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(main._generation_lock.locked())

    def test_busy_worker_is_429_without_queuing(self):
        self._authenticate()
        started = threading.Event()
        release = threading.Event()
        cutout = _png(Image.new("RGBA", (2, 2), (0, 0, 0, 0)))
        _, upload, insert = self._successful_storage()
        first = {}

        def blocking_worker(source):
            started.set()
            release.wait(10)
            return cutout

        def first_request():
            try:
                first["response"] = self._post(_encoded(_tiny_png()))
            except BaseException as exc:  # surfaced as an assertion below
                first["error"] = exc

        with patch.object(service, "remove_background_png", side_effect=blocking_worker) as worker, upload, insert:
            thread = threading.Thread(target=first_request)
            thread.start()
            try:
                self.assertTrue(started.wait(10), "worker never started")
                # Validation stays ahead of the lock: bad input outranks 429.
                self.assertEqual(self._post("!" * 2_800_001).status_code, 413)
                second = self._post(_encoded(_tiny_png()))
                self.assertEqual(second.status_code, 429)
            finally:
                release.set()
                thread.join(10)

        self.assertFalse(thread.is_alive())
        self.assertNotIn("error", first)
        self.assertEqual(first["response"].status_code, 200)
        self.assertEqual(worker.call_count, 1)


if __name__ == "__main__":
    unittest.main()
