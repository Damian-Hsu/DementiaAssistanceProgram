from __future__ import annotations
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column
from . import ORMBase, TimestampMixin

__all__ = ["Table"]


class SettingsTable(ORMBase, TimestampMixin):
    """系統設定表格"""
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True, nullable=False, unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # 設定值（JSON 字串）
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # 設定描述


Table = SettingsTable

