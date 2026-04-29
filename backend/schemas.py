from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    user_id: UUID
    images: list[str] | None = None
    num_inference_steps: int = Field(default=50, ge=20, le=75)
    guidance_scale: float = Field(default=1.5, ge=1.0, le=5.0)


class Generation(BaseModel):
    id: UUID
    user_id: UUID
    prompt: str
    image_path: str
    public_url: str
    created_at: datetime
