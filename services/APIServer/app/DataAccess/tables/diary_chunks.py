from __future__ import annotations
import uuid
from datetime import date, datetime
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import String, Date, Text, ForeignKey, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector

from . import ORMBase, TimestampMixin, TimestampSchema
from .__Function import create_uuid7

__all__ = ["Schema", "Table"]

class Schema(BaseModel):
    """diary_chunks 的基礎 I/O 欄位"""
    daily_summary_id: uuid.UUID
    chunk_text: str
    chunk_index: int
    embedding: list[float] | None = None
    is_processed: bool = False

    model_config = ConfigDict(from_attributes=True)

class DiaryChunksTable(ORMBase, TimestampMixin):
    __tablename__ = "diary_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=create_uuid7
    )
    daily_summary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("daily_summaries.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[Vector | None] = mapped_column(Vector(1024), nullable=True)
    is_processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

Table = DiaryChunksTable

