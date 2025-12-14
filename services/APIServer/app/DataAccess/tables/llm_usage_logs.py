from __future__ import annotations

import uuid
from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSONB

from . import ORMBase, TimestampMixin
from .__Function import create_uuid7

__all__ = ["Table"]


class LLMUsageLogsTable(ORMBase, TimestampMixin):
    """LLM 使用量紀錄（用於統計 Token 使用量與 AI 助手回覆次數）。"""

    __tablename__ = "llm_usage_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=create_uuid7,
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # chat / diary / compute
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)  # google / openai / ...
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)  # 例如 gemini-2.5-flash-lite

    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    assistant_replies: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


Table = LLMUsageLogsTable


