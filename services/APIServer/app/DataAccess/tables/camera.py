from __future__ import annotations
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import String, DateTime, Text, Float, ForeignKey, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, ARRAY, CIDR

from . import ORMBase, TimestampMixin, TimestampSchema
from .__Function import create_uuid7
from .__Enumeration import CameraStatus, CameraStatusEnum

__all__ = ["Schema", "Table"]

class CameraTable(ORMBase, TimestampMixin):
    __tablename__ = "camera"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=create_uuid7
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[CameraStatus] = mapped_column(CameraStatusEnum, default=CameraStatus.inactive, nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(64), unique=True, nullable=True, index=True)
    token_version: Mapped[int] = mapped_column(nullable=False, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_publishers: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    
Table = CameraTable