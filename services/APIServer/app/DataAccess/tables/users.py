from __future__ import annotations
from datetime import date
from pydantic import BaseModel, Field
from sqlalchemy import String, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from . import ORMBase, TimestampMixin, TimestampSchema
from .__Enumeration import Role, Gender, DementiaLevel
from .__Enumeration import RoleEnum, GenderEnum, DementiaLevelEnum

__all__ = ["Schema",
           "Table"]

class Schema(BaseModel):
    id: int = Field(ge=1)
    account: str = Field(max_length=50)
    name: str = Field(max_length=100)
    role: Role = Role.user
    gender: Gender
    dementia_level: DementiaLevel = DementiaLevel.normal
    birthday: date
    phone: str = Field(max_length=20)
    email: str = Field(max_length=100)
    headshot_url: str | None = None
    password_hash: str = Field(max_length=256)
    active: bool = True



class UserTable(ORMBase, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[Role] = mapped_column(RoleEnum, nullable=False, default=Role.user)
    gender: Mapped[Gender] = mapped_column(GenderEnum, nullable=False)
    dementia_level: Mapped[DementiaLevel] = mapped_column(DementiaLevelEnum,nullable=False, default=DementiaLevel.normal)
    birthday: Mapped[date] = mapped_column(nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    headshot_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    settings: Mapped[dict|None] = mapped_column(JSONB,nullable=True)

Table = UserTable
