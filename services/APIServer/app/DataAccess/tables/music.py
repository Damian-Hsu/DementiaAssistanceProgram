from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Integer, String, Text, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from . import ORMBase, TimestampMixin, TimestampSchema
from .__Function import create_uuid7

__all__ = ["Schema", "Table"]


class Schema(BaseModel):
    name: str
    uploader_user_id: int
    composer: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[dict] = None
    duration: Optional[float] = None
    s3_key: str
    content_type: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class MusicTable(ORMBase, TimestampMixin):
    __tablename__ = "music"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=create_uuid7,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    uploader_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    composer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    s3_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)


Table = MusicTable

