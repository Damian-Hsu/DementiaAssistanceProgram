from __future__ import annotations

import uuid
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import String, DateTime, Text, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB

from . import ORMBase, TimestampMixin, TimestampSchema
from .__Function import create_uuid7
from .__Enumeration import JobStatus
from .__Enumeration import JobStatusEnum

__all__ = ["Schema", "Table"]

class InferenceJobsTable(ORMBase, TimestampMixin):
    __tablename__ = "inference_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=create_uuid7,
    )
    type: Mapped[str|None] = mapped_column(String(128), nullable=False)
    status: Mapped[JobStatus] = mapped_column(JobStatusEnum, nullable=False, default=JobStatus.pending)
    input_type: Mapped[str|None] = mapped_column(String(128), nullable=False)
    input_url: Mapped[str|None] = mapped_column(Text, nullable=False)
    output_url: Mapped[str|None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    duration: Mapped[float|None] = mapped_column(Float, nullable=True)
    error_code: Mapped[str|None] = mapped_column(String(64),nullable=True)
    error_message: Mapped[str|None] = mapped_column(Text, nullable=True)
    params: Mapped[dict|None] = mapped_column(JSONB,nullable=True)
    metrics: Mapped[dict|None] = mapped_column(JSONB,nullable=True)

Table = InferenceJobsTable