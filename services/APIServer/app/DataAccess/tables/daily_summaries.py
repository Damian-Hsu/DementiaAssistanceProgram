from __future__ import annotations
import uuid
from datetime import date
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import String, Date, Text, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from . import ORMBase, TimestampMixin
from .__Function import create_uuid7

__all__ = ["Schema", "Table"]

class Schema(BaseModel):
    """daily_summaries 的基礎 I/O 欄位"""
    user_id: int
    date: date
    summary_text: str | None = None
    
    model_config = ConfigDict(from_attributes=True)

class DailySummaryTable(ORMBase, TimestampMixin):
    __tablename__ = "daily_summaries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=create_uuid7
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 確保同一使用者同一天只有一個摘要
    __table_args__ = (
        UniqueConstraint('user_id', 'date', name='uq_user_date_summary'),
    )

Table = DailySummaryTable

