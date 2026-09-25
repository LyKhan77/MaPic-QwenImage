import os
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch

from PIL import Image

from backend.services import remove_background_service as service

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


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
        stored = Image.new("RGB", (6, 2), (200, 100, 50))
        exif = stored.getexif()
        exif[274] = 6  # rotate 90 CW when displayed
        buffer = BytesIO()
        stored.save(buffer, format="JPEG", exif=exif)
        model = Image.new("RGBA", (2, 6), (0, 0, 0, 255))

        with patch.object(service, "_session_factory", return_value=object()), patch.object(
            service, "_extract", return_value=_png(model)
        ):
            output = service.remove_background_png(buffer.getvalue())

        with Image.open(BytesIO(output)) as result:
            self.assertEqual(result.size, (2, 6))

    def test_missing_weights_raises_model_unavailable_without_network(self):
        source = _png(Image.new("RGBA", (4, 4), (0, 0, 0, 255)))

        with tempfile.TemporaryDirectory() as empty_home:
            with patch.dict(os.environ, {"REMBG_HOME": empty_home}), patch.object(
                service, "_session_factory", side_effect=AssertionError("session must not be built")
            ):
                with self.assertRaises(service.ModelUnavailableError):
                    service.remove_background_png(source)

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


if __name__ == "__main__":
    unittest.main()
