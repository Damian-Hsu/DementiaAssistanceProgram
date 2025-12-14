from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import String, Date, Text, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from . import ORMBase, TimestampMixin
from .__Function import create_uuid7

__all__ = ["Table"]


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

