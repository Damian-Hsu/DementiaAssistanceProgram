from __future__ import annotations
import uuid
from datetime import date
from sqlalchemy import String, Date, Text, ForeignKey, Integer, Float
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB

from . import ORMBase, TimestampMixin
from .__Function import create_uuid7

__all__ = ["Table", "SegmentTable"]

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

