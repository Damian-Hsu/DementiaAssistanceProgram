from __future__ import annotations
import uuid
from datetime import date, datetime
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import String, Date, Text, ForeignKey, Integer, Float, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector

from . import ORMBase, TimestampMixin, TimestampSchema
from .__Function import create_uuid7

__all__ = ["Schema", "Table", "SegmentSchema", "SegmentTable"]

class Schema(BaseModel):
    """vlog 的基礎 I/O 欄位"""
    user_id: int
    title: str | None = None
    target_date: date
    duration: float | None = None
    status: str = 'pending'
    settings: dict | None = None
    progress: float | None = None
    status_message: str | None = None

    model_config = ConfigDict(from_attributes=True)

class SegmentSchema(BaseModel):
    vlog_id: uuid.UUID
    recording_id: uuid.UUID
    event_id: uuid.UUID | None = None
    start_offset: float
    end_offset: float
    sequence_order: int
    
    model_config = ConfigDict(from_attributes=True)

class VlogsTable(ORMBase, TimestampMixin):
    __tablename__ = "vlogs"

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
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_s3_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # 縮圖 S3 路徑
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default='pending', nullable=False) # pending, processing, completed, failed
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

class VlogSegmentsTable(ORMBase, TimestampMixin):
    __tablename__ = "vlog_segments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=create_uuid7
    )
    vlog_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vlogs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recordings.id"),
        nullable=False
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id"),
        nullable=True
    )
    start_offset: Mapped[float] = mapped_column(Float, nullable=False)
    end_offset: Mapped[float] = mapped_column(Float, nullable=False)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)

Table = VlogsTable
SegmentTable = VlogSegmentsTable

