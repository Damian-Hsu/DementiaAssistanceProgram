from __future__ import annotations
from datetime import datetime
import uuid

from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Float, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB, BIGINT
from sqlalchemy.orm import Mapped, mapped_column

from . import ORMBase, TimestampMixin, TimestampSchema
from .__Function import create_uuid7
from .__Enumeration import UploadStatus, UploadStatusEnum

__all__ = ["Schema", "Table"]


class Schema(BaseModel):
    id: uuid.UUID
    url: str 
    user_id: int
    camera_id: uuid.UUID | None = None
    duration: float | None = Field(default=None, ge=0)
    is_processed: bool = False
    is_embedding: bool = False
    start_time: datetime | None = None
    video_metadata: dict | None = None

    model_config = ConfigDict(from_attributes=True)
    


class RecordingsTable(ORMBase, TimestampMixin):
    __tablename__ = "recordings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=create_uuid7
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("camera.id"),
        nullable=True
    )
    s3_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_embedding: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    size_bytes: Mapped[int | None] = mapped_column(BIGINT, nullable=True)
    upload_status: Mapped[UploadStatus] = mapped_column(UploadStatusEnum, nullable=False, default=UploadStatus.pending)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    video_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

Table = RecordingsTable