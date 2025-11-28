from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import String, DateTime, Text, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from pgvector.sqlalchemy import Vector

from . import ORMBase, TimestampMixin, TimestampSchema
from .__Function import create_uuid7

__all__ = ["Schema", "Table"]


class Schema(BaseModel):
    """events 的基礎 I/O 欄位（不含 id/時間戳）。"""
    recording_id: uuid.UUID | None = None
    action: str | None = Field(default=None, max_length=128)
    scene:  str | None = Field(default=None, max_length=128)
    summary: str | None = None
    objects: list[str] | None = None
    start_time: datetime | None = None
    duration: float | None = Field(default=None, ge=0)

    model_config = ConfigDict(from_attributes=True)

class EventsTable(ORMBase, TimestampMixin):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=create_uuid7
    )
    # 下次要更新的時候新增(10/20/2025新增)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    recording_id: Mapped[uuid.UUID|None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id"),
        nullable=True,
        index=True
    )
    action: Mapped[str|None] = mapped_column(String(128), nullable=True)
    scene:  Mapped[str|None] = mapped_column(String(128), nullable=True)
    summary: Mapped[str|None] = mapped_column(Text, nullable=True)
    objects: Mapped[list[str]|None] = mapped_column(ARRAY(String), nullable=True)
    start_time: Mapped[datetime|None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration: Mapped[float|None] = mapped_column(
        Float, nullable=True
    )
    embedding: Mapped[Vector | None] = mapped_column(Vector(1024), nullable=True)
Table = EventsTable