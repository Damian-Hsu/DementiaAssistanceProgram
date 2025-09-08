# -*- coding: utf-8 -*-
from pydantic import BaseModel, EmailStr
from datetime import date, datetime
from typing import Optional
from ...DataAccess.tables import __Enumeration as TE


# ======= DTOs =======
class SignupRequestDTO(BaseModel):
    account: str
    name: str
    gender: TE.Gender
    birthday: date
    phone: str
    email: EmailStr
    headshot_url: str | None = None
    password: str

class LoginRequestDTO(BaseModel):
    account: str
    password: str

class LoginResponseDTO(BaseModel):
    access_token: str
    token_type: str = "bearer"

class ChangePasswordRequestDTO(BaseModel):
    old_password: str
    new_password: str

class UpdateUserProfileDTO(BaseModel):
    name: Optional[str] = None
    gender: Optional[TE.Gender] = None
    birthday: Optional[datetime] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    headshot_url: Optional[str] = None

