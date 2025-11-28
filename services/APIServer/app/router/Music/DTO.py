from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict
from typing import Optional, List


class MusicRead(BaseModel):
    id: str
    name: str
    composer: Optional[str] = None
    description: Optional[str] = None
    duration: Optional[float] = None
    metadata: Optional[dict] = None
    uploader_user_id: int
    uploader_name: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    content_type: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class MusicAdminRead(MusicRead):
    s3_key: str
    content_type: Optional[str] = None


class MusicListResponse(BaseModel):
    items: List[MusicRead]
    total: int


class MusicUrlResponse(BaseModel):
    url: str
    ttl: int
    expires_at: int

