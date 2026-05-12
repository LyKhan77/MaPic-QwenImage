import os
from dotenv import load_dotenv

load_dotenv()


def _get_env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    if value is None:
        return ""
    return value


SUPABASE_URL = _get_env("SUPABASE_URL", required=True)
SUPABASE_SERVICE_ROLE_KEY = _get_env("SUPABASE_SERVICE_ROLE_KEY", required=True)

GLM_IMAGE_API_URL = _get_env("GLM_IMAGE_API_URL", "http://localhost:30000")
MODEL_NAME = "glm-image"

CORS_ORIGINS = _get_env("CORS_ORIGINS", "http://localhost:5151,http://localhost:5152,http://127.0.0.1:5151,http://127.0.0.1:5152,https://frontend-one-mu-qq21mhpswl.vercel.app")
