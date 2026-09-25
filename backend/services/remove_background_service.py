"""CPU background removal worker (rembg + isnet-general-use ONNX).

Inference runs locally on CPU; nothing here touches Qwen/ComfyUI or the network.
Model weights are resolved from disk before a session is built, so a missing
weight file fails fast instead of triggering an implicit download.
"""

import os
import threading
from io import BytesIO

from PIL import Image, ImageChops, ImageOps

MODEL_NAME = "isnet-general-use"

_session = None
_session_lock = threading.Lock()


class RemoveBackgroundError(Exception):
    """Raised when the cutout pipeline cannot produce a result."""


class ModelUnavailableError(RemoveBackgroundError):
    """Raised when the local ONNX weights for MODEL_NAME are missing."""


def _candidate_paths() -> list[str]:
    """Every path rembg may resolve `{MODEL_NAME}.onnx` from, in its own order."""
    legacy_home = os.path.expanduser(
        os.environ.get(
            "U2NET_HOME", os.path.join(os.environ.get("XDG_DATA_HOME", "~"), ".u2net")
        )
    )
    if os.environ.get("U2NET_HOME"):
        rembg_home = legacy_home
    else:
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        default = os.path.join(xdg_data_home, "rembg") if xdg_data_home else "~/.rembg"
        rembg_home = os.path.expanduser(os.environ.get("REMBG_HOME", default))
    return [
        os.path.join(rembg_home, "models", MODEL_NAME, f"{MODEL_NAME}.onnx"),
        os.path.join(legacy_home, f"{MODEL_NAME}.onnx"),
    ]


def _fallback_model_path() -> str | None:
    for candidate in _candidate_paths():
        if os.path.isfile(candidate):
            return candidate
    return None


def _model_path() -> str | None:
    """Path rembg will use, or None. Never triggers a download."""
    try:
        from rembg.sessions.dis_general_use import DisSession
    except ImportError:
        return _fallback_model_path()
    return DisSession.resolve_existing(f"{MODEL_NAME}.onnx")


def _session_factory() -> object:
    from rembg import new_session

    return new_session(MODEL_NAME)


def _extract(image_bytes: bytes, session: object) -> bytes:
    from rembg import remove

    return remove(image_bytes, session=session)


def _session_for_model():
    global _session
    if _session is None:
        with _session_lock:
            if _session is None:
                if _model_path() is None:
                    searched = ", ".join(_candidate_paths())
                    raise ModelUnavailableError(
                        f"Local weights for {MODEL_NAME} not found; refusing to download. "
                        f"Searched: {searched}"
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
            if "A" not in cutout.getbands():
                raise RemoveBackgroundError(
                    f"Cutout mode {cutout.mode} has no alpha channel; refusing to return an "
                    "opaque result."
                )
            mask = cutout.convert("RGBA")

        if mask.size != normalised.size:
            raise RemoveBackgroundError(
                f"Cutout size {mask.size} does not match source size {normalised.size}."
            )

        alpha = mask.getchannel("A")
        normalised.putalpha(ImageChops.darker(normalised.getchannel("A"), alpha))
        return _to_png(normalised)
    except ModelUnavailableError:
        raise
    except RemoveBackgroundError:
        raise
    except Exception as error:
        raise RemoveBackgroundError(str(error)) from error
