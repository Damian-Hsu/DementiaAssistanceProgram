from __future__ import annotations
from pydantic import BaseModel, EmailStr, field_validator
from datetime import date
import re

class SignupRequestDTO(BaseModel):
    account: str
    name: str
    gender: str
    birthday: date
    phone: str
    email: EmailStr
    password: str

    @field_validator('account')
    @classmethod
    def validate_account(cls, v: str) -> str:
        if not v or not isinstance(v, str):
            raise ValueError('帳號不能為空')
        
        v = v.strip()
        if v != v.strip() or ' ' in v:
            raise ValueError('帳號前後不可有空格')
        
        if len(v) < 6:
            raise ValueError('帳號至少需要6個字元')
        
        if len(v) > 30:
            raise ValueError('帳號最多30個字元')
        
        # 只允許英文字母、數字、.、_
        if not re.match(r'^[a-zA-Z0-9._]+$', v):
            raise ValueError('帳號只能包含英文字母、數字、.、_，不可有空格')
        
        return v

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not v or not isinstance(v, str):
            raise ValueError('密碼不能為空')
        
        if len(v) < 8:
            raise ValueError('密碼至少需要8個字元')
        
        if len(v) > 30:
            raise ValueError('密碼最多30個字元')
        
        # 只允許英文字母、數字、.、_
        if not re.match(r'^[a-zA-Z0-9._]+$', v):
            raise ValueError('密碼只能包含英文字母、數字、.、_')
        
        return v

class LoginRequestDTO(BaseModel):
    account: str
    password: str

    @field_validator('account')
    @classmethod
    def validate_account(cls, v: str) -> str:
        if not v or not isinstance(v, str):
            raise ValueError('帳號不能為空')
        
        v = v.strip()
        if v != v.strip() or ' ' in v:
            raise ValueError('帳號前後不可有空格')
        
        if len(v) < 6:
            raise ValueError('帳號至少需要6個字元')
        
        if len(v) > 30:
            raise ValueError('帳號最多30個字元')
        
        # 只允許英文字母、數字、.、_
        if not re.match(r'^[a-zA-Z0-9._]+$', v):
            raise ValueError('帳號只能包含英文字母、數字、.、_，不可有空格')
        
        return v

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not v or not isinstance(v, str):
            raise ValueError('密碼不能為空')
        
        if len(v) < 8:
            raise ValueError('密碼至少需要8個字元')
        
        if len(v) > 30:
            raise ValueError('密碼最多30個字元')
        
        # 只允許英文字母、數字、.、_
        if not re.match(r'^[a-zA-Z0-9._]+$', v):
            raise ValueError('密碼只能包含英文字母、數字、.、_')
        
        return v

class LoginResponseDTO(BaseModel):
    access_token: str
    token_type: str = "bearer"
