from __future__ import annotations
from datetime import datetime
from hashlib import sha256
import uuid
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, ARRAY

from . import ORMBase, TimestampMixin  # 你既有的 Base / Mixin
from . import users  # 需要 owner 關聯（你已有 users.Table）
from .__Function import create_uuid7

__all__ = ["Schema", "Table"]

class ApiKeyTable(ORMBase, TimestampMixin):
    __tablename__ = "api_keys"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=create_uuid7)
    
    # 管理端顯示用名稱
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # sha256(token) 的十六進位字串（64 字元）
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scopes: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    # 可選配額欄位
    rate_limit_per_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped[users.Table] = relationship(lazy="joined")

Table = ApiKeyTable