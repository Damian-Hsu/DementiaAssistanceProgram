from __future__ import annotations
from sqlalchemy import Integer, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from . import ORMBase, TimestampMixin
from . import users

__all__ = ["Table"]


class ApiKeyBlacklistTable(ORMBase, TimestampMixin):
    """API Key 黑名單表格（禁止使用預設 API Key 的使用者）"""
    __tablename__ = "api_key_blacklist"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        unique=True,
        index=True
    )  # 使用者 ID
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 禁止原因
    
    # 關聯
    user: Mapped[users.Table] = relationship(lazy="joined")


Table = ApiKeyBlacklistTable

