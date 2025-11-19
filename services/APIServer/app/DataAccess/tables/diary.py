from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import String, Date, Text, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from . import ORMBase, TimestampMixin, TimestampSchema
from .__Function import create_uuid7

__all__ = ["Schema", "Table"]


class Schema(BaseModel):
    """diary 的基礎 I/O 欄位（不含 id/時間戳）。"""
    user_id: int
    diary_date: date
    content: str | None = Field(default=None, max_length=1000)
    events_hash: str | None = Field(default=None, max_length=64)

    model_config = ConfigDict(from_attributes=True)


class DiaryTable(ORMBase, TimestampMixin):
    __tablename__ = "diary"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=create_uuid7
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )
    diary_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True
    )
    content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )
    events_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True
    )


Table = DiaryTable

