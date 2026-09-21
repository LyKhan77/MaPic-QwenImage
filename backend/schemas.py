from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

try:
    from backend.config import QWEN_DEFAULT_RESOLUTION
except ModuleNotFoundError:
    from config import QWEN_DEFAULT_RESOLUTION


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    user_id: UUID
    images: list[str] | None = Field(default=None, max_length=10)
    negative_prompt: str | None = Field(default=None, max_length=2000)
    true_cfg_scale: float = Field(default=1.0, ge=1.0, le=3.0)
    num_inference_steps: int = Field(default=40, ge=20, le=75)
    resolution: Literal[1024, 2048] = QWEN_DEFAULT_RESOLUTION


class Generation(BaseModel):
    id: UUID
    user_id: UUID
    prompt: str
    image_path: str
    public_url: str
    created_at: datetime


class ActiveGeneration(BaseModel):
    id: str
    user_id: str
    prompt: str
    elapsed_seconds: int
    status: str = "running"
    num_inference_steps: int = 40
    num_ref_images: int = 0
    resolution: int = 2048
    cfg_enabled: bool = False
