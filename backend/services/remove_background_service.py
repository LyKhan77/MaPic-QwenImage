"""CPU background removal worker (rembg + isnet-general-use ONNX).

Inference runs locally on CPU; nothing here touches Qwen/ComfyUI or the network.
Model weights are resolved from disk before a session is built, so a missing
weight file fails fast instead of triggering an implicit download.
"""

import os
from io import BytesIO

from PIL import Image, ImageChops, ImageOps

MODEL_NAME = "isnet-general-use"

_session = None


class RemoveBackgroundError(Exception):
    """Raised when the cutout pipeline cannot produce a result."""


class ModelUnavailableError(RemoveBackgroundError):
    """Raised when the local ONNX weights for MODEL_NAME are missing."""


def _model_path() -> str | None:
    home = os.environ.get("REMBG_HOME")
    if not home:
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        home = os.path.join(xdg_data_home, "rembg") if xdg_data_home else os.path.join(
            os.path.expanduser("~"), ".rembg"
        )
    for candidate in (
        os.path.join(home, "models", MODEL_NAME, f"{MODEL_NAME}.onnx"),
        os.path.join(home, f"{MODEL_NAME}.onnx"),
    ):
        if os.path.isfile(candidate):
            return candidate
    return None


def _session_factory():
    from rembg import new_session

    return new_session(MODEL_NAME)


def _extract(image_bytes: bytes, session) -> bytes:
    from rembg import remove

    return remove(image_bytes, session=session)


def _session_for_model():
    global _session
    if _session is None:
        if _model_path() is None:
            raise ModelUnavailableError(
                f"Local weights for {MODEL_NAME} not found; refusing to download."
            )
        _session = _session_factory()
    return _session


def _to_png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def remove_background_png(source: bytes) -> bytes:
    """Return a PNG RGBA of the same size as the EXIF-normalised source.

    RGB is taken from the source; alpha is the model mask combined with the
    source's own alpha. Raises ModelUnavailableError when local weights are
    missing, RemoveBackgroundError for any other processing failure.
    """
    try:
        with Image.open(BytesIO(source)) as opened:
            opened.load()
            normalised = ImageOps.exif_transpose(opened).convert("RGBA")

        cutout_bytes = _extract(_to_png(normalised), _session_for_model())

        with Image.open(BytesIO(cutout_bytes)) as cutout:
            cutout.load()
            mask = cutout.convert("RGBA")

        if mask.size != normalised.size:
            raise RemoveBackgroundError(
                f"Cutout size {mask.size} does not match source size {normalised.size}."
            )

        result = normalised.copy()
        result.putalpha(ImageChops.darker(normalised.getchannel("A"), mask.getchannel("A")))
        return _to_png(result)
    except ModelUnavailableError:
        raise
    except RemoveBackgroundError:
        raise
    except Exception as error:
        raise RemoveBackgroundError(str(error)) from error
