import io
from typing import Any
from uuid import UUID, uuid4

from supabase import Client, create_client

try:
    from backend.config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL
except ModuleNotFoundError:
    from config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL


BUCKET_NAME = "generated_images"


class SupabaseError(Exception):
    pass


class GenerationNotFound(SupabaseError):
    """Baris tidak ada, atau ada tapi bukan milik user yang meminta."""


supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def _extract_public_url(response: Any) -> str | None:
    if isinstance(response, str):
        return response

    if isinstance(response, dict):
        if isinstance(response.get("publicUrl"), str):
            return response["publicUrl"]
        if isinstance(response.get("publicURL"), str):
            return response["publicURL"]

        data = response.get("data")
        if isinstance(data, dict):
            if isinstance(data.get("publicUrl"), str):
                return data["publicUrl"]
            if isinstance(data.get("publicURL"), str):
                return data["publicURL"]

    return None


def _raise_on_error(response: Any, fallback_message: str) -> None:
    if response is None:
        raise SupabaseError(fallback_message)

    error = getattr(response, "error", None)
    if error:
        raise SupabaseError(str(error))

    if isinstance(response, dict) and response.get("error"):
        raise SupabaseError(str(response["error"]))


def upload_image(user_id: UUID, image_bytes: bytes) -> tuple[str, str]:
    file_path = f"{user_id}/{uuid4()}.png"
    # file_data = io.BytesIO(image_bytes) # Removed: Library expects raw bytes or path

    try:
        response = supabase.storage.from_(BUCKET_NAME).upload(
            path=file_path,
            file=image_bytes,
            file_options={"content-type": "image/png"},
        )
        _raise_on_error(response, "Failed to upload image to storage")

        public_url = supabase.storage.from_(BUCKET_NAME).get_public_url(file_path)
        # Verify it's a string, if the SDK changes to return an object with data key again, we might need adjustment
        # But standard Python supabase client returns string.
        if not isinstance(public_url, str):
             # Fallback for older versions or if it returns an object
             public_url = _extract_public_url(public_url)
             
        if not public_url:
            raise SupabaseError("Failed to resolve public URL")

        return file_path, public_url
    except SupabaseError:
        raise
    except Exception as exc:
        raise SupabaseError("Unexpected storage error") from exc


def insert_generation(user_id: UUID, prompt: str, image_path: str, public_url: str) -> dict:
    payload = {
        "user_id": str(user_id),
        "prompt": prompt,
        "image_path": image_path,
        "public_url": public_url,
    }

    response = supabase.table("generations").insert(payload).execute()
    _raise_on_error(response, "Failed to insert generation")

    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")

    if not data:
        raise SupabaseError("No data returned from insert")

    if isinstance(data, list):
        return data[0]

    return data


def fetch_history(user_id: UUID) -> list[dict]:
    response = (
        supabase.table("generations")
        .select("*")
        .eq("user_id", str(user_id))
        .order("created_at", desc=True)
        .execute()
    )
    _raise_on_error(response, "Failed to fetch history")

    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")

    if not data:
        return []

    return data

def delete_generation(gen_id: UUID, user_id: UUID) -> None:
    # 1. Cari record milik user ini — sekaligus memastikan barisnya bukan milik
    #    user lain. Record milik orang lain tampak sebagai "tidak ada".
    response = (
        supabase.table("generations")
        .select("image_path")
        .eq("id", str(gen_id))
        .eq("user_id", str(user_id))
        .execute()
    )
    _raise_on_error(response, "Failed to find generation")

    rows = getattr(response, "data", None)
    if rows is None and isinstance(response, dict):
        rows = response.get("data")
    if not rows:
        raise GenerationNotFound("Generation not found")

    image_path = rows[0].get("image_path")

    # 2. Delete file from storage
    if image_path:
        storage_res = supabase.storage.from_(BUCKET_NAME).remove([image_path])
        # We don't raise error here if storage delete fails, just log it, 
        # but for now we proceed to delete DB record.

    # 3. Delete DB record
    del_res = (
        supabase.table("generations")
        .delete()
        .eq("id", str(gen_id))
        .eq("user_id", str(user_id))
        .execute()
    )
    _raise_on_error(del_res, "Failed to delete generation record")