from __future__ import annotations
from pydantic import BaseModel, EmailStr
from datetime import date

class SignupRequestDTO(BaseModel):
    account: str
    name: str
    gender: str
    birthday: date
    phone: str
    email: EmailStr
    password: str

class LoginRequestDTO(BaseModel):
    account: str
    password: str

class LoginResponseDTO(BaseModel):
    access_token: str
    token_type: str = "bearer"
