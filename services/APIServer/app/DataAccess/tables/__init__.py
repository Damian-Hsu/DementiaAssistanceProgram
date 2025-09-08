"""
檔案內所有的檔名為表格名稱(除去Enumeration與Function)，每個表格都有對應的不同模型：
Schema - 所有表格的基底(透過pydantic)，用於限制傳入傳出的基礎欄位限制，與Table對齊
Table - 表格模型 (繼承自 Base)
{ApiName}_{input/output} - 其他自訂義的不同API特殊回傳的

所有非table欄位的寫在Enumeration與Function
"""
__all__ = ["ORMBase",
           "TimestampMixin",
           "TimestampMixinSchema"]

from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, declared_attr
from sqlalchemy import DateTime, func
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, field_serializer

# 讓其他table可以繼承這個Base，同根
class ORMBase(AsyncAttrs, DeclarativeBase):
    pass
class TimestampMixin:
    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            server_default=func.timezone("UTC", func.now()),
            nullable=False,
        )

    @declared_attr
    def updated_at(cls) -> Mapped[datetime | None]:
        # 在 UPDATE 時由資料庫端更新為 UTC 時間
        return mapped_column(
            DateTime(timezone=True),
            onupdate=func.timezone("UTC", func.now()),
            nullable=True,
        )
    
class TimestampSchema(BaseModel):
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at", "updated_at", when_used="json")
    def _dt_to_z(cls, v: datetime | None) -> str | None:
        if v is None:
            return None
        # 確保是 UTC，並輸出以 Z 結尾的 ISO 8601
        return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")