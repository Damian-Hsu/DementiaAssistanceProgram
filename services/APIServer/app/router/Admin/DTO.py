from __future__ import annotations
from pydantic import BaseModel
from uuid import UUID


class ApiKeyCreateDTO(BaseModel):
    name: str
    owner_id: int   
    rate_limit_per_min: int | None = None
    quota_per_day: int | None = None
    scopes: list[str] | None = None  # 可選作用域


class ApiKeyOutDTO(BaseModel):
    id: UUID
    name: str
    owner_id: int
    active: bool
    rate_limit_per_min: int | None = None
    quota_per_day: int | None = None
    scopes: list[str] | None = None

    class Config:
        from_attributes = True  # 允許 SQLAlchemy ORM 自動轉換


class ApiKeySecretOutDTO(ApiKeyOutDTO):
    token: str  # 建立或 rotate 時才回傳一次


class ApiKeyPatchDTO(BaseModel):
    name: str | None = None
    active: bool | None = None
    rate_limit_per_min: int | None = None
    quota_per_day: int | None = None
    scopes: list[str] | None = None
