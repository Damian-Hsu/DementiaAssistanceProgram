from __future__ import annotations
import uuid
from sqlalchemy import Text, ForeignKey, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector

from . import ORMBase, TimestampMixin
from .__Function import create_uuid7

__all__ = ["Table"]

class DiaryChunksTable(ORMBase, TimestampMixin):
    __tablename__ = "diary_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=create_uuid7
    )
    diary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("diary.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[Vector | None] = mapped_column(Vector(1024), nullable=True)
    is_processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

Table = DiaryChunksTable

