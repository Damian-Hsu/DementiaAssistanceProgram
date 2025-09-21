# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...DataAccess.Connect import get_session
from ...DataAccess.tables import users
from ...security.jwt_manager import JWTManager
from .DTO import (
    SignupRequestDTO,
    LoginRequestDTO,
    LoginResponseDTO,
    ChangePasswordRequestDTO,
    UpdateUserProfileDTO,
)

WWW_BEARER = {"WWW-Authenticate": "Bearer"}


# ======= Service（商業邏輯）=======
class UserService:
    """使用者註冊 / 登入 / 修改資料 / 修改密碼 的應用服務。"""

    def __init__(self, jwt_manager: Optional[JWTManager] = None):
        self.jwt = jwt_manager or JWTManager()

    # 註冊：成功直接回 access token
    async def signup_user(self, db: AsyncSession, body: SignupRequestDTO) -> LoginResponseDTO:
        
        # 檢查 account
        stmt = select(users.Table).where(users.Table.account == body.account)
        exists = await db.execute(stmt)
        if exists.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="帳號已存在")

        # 檢查 email
        stmt = select(users.Table).where(users.Table.email == body.email)
        exists = await db.execute(stmt)
        if exists.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email 已被使用")
        
        # 檢查 phone
        stmt = select(users.Table).where(users.Table.phone == body.phone)
        exists = await db.execute(stmt)
        if exists.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="phone 已被使用")
        
        hashed = self.jwt.hash_password(body.password)
        user = users.Table(
            account=body.account,
            name=body.name,
            gender=body.gender,
            birthday=body.birthday,
            phone=body.phone,
            email=body.email,
            headshot_url=body.headshot_url,
            password_hash=hashed,
            role=users.Role.user,
            active=True
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        token = self._issue_token(user)
        return LoginResponseDTO(access_token=token)
    
    async def signup_admin(self, db: AsyncSession, body: SignupRequestDTO) -> LoginResponseDTO:
        # 檢查 account
        stmt = select(users.Table).where(users.Table.account == body.account)
        exists = await db.execute(stmt)
        if exists.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="帳號已存在")

        # 檢查 email
        stmt = select(users.Table).where(users.Table.email == body.email)
        exists = await db.execute(stmt)
        if exists.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email 已被使用")
        # 檢查 phone
        stmt = select(users.Table).where(users.Table.phone == body.phone)
        exists = await db.execute(stmt)
        if exists.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="phone 已被使用")
        
        hashed = self.jwt.hash_password(body.password)
        user = users.Table(
            account=body.account,
            name=body.name,
            gender=body.gender,
            birthday=body.birthday,
            phone=body.phone,
            email=body.email,
            password_hash=hashed,
            headshot_url=body.headshot_url,
            role=users.Role.admin,
            active=True
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        token = self._issue_token(user)
        return LoginResponseDTO(access_token=token)
    # 登入
    async def login_user(self, db: AsyncSession, body: LoginRequestDTO) -> LoginResponseDTO:
        stmt = select(users.Table).where(users.Table.account == body.account)
        result = await db.execute(stmt)
        user: Optional[users.Table] = result.scalar_one_or_none()

        if not user or not self.jwt.verify_password(body.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="帳號或密碼錯誤",
                headers=WWW_BEARER,
            )
        
        if not user.active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="帳號已停用",
                headers=WWW_BEARER,
            )

        token = self._issue_token(user)
        return LoginResponseDTO(access_token=token)

    # 修改基本資料（不含密碼）
    async def update_profile(
        self, db: AsyncSession, current_user: users.Table, body: UpdateUserProfileDTO
    ) -> dict:
        patch = body.model_dump(exclude_unset=True)

        # 檢查 email 唯一性
        new_email = patch.get("email")
        if new_email and new_email != current_user.email:
            stmt = (
                select(users.Table)
                .where(users.Table.email == new_email)
                .where(users.Table.id != current_user.id)
            )
            exists = await db.execute(stmt)
            if exists.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Email 已被使用")

        for k, v in patch.items():
            setattr(current_user, k, v)

        db.add(current_user)
        await db.commit()
        await db.refresh(current_user)

        return {"msg": "資料已更新", "user": self._public_user(current_user)}

    # 修改密碼
    async def change_password(
        self, db: AsyncSession, current_user: users.Table, body: ChangePasswordRequestDTO
    ) -> dict:
        if not self.jwt.verify_password(body.old_password, current_user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="舊密碼不正確",
                headers=WWW_BEARER,
            )
        new_hashed = self.jwt.hash_password(body.new_password)
        current_user.password_hash = new_hashed

        db.add(current_user)
        await db.commit()
        return {"msg": "密碼已成功更新"}

    # ---- internal helpers ----
    def _issue_token(self, user: users.Table) -> str:
        return self.jwt.create_token(
            subject=str(user.id),
            extra={"account": user.account, "role": user.role},
        )

    @staticmethod
    def _public_user(u: users.Table) -> dict:
        return {
            "id": u.id,
            "account": u.account,
            "name": u.name,
            "gender": u.gender,
            "birthday": u.birthday,
            "phone": u.phone,
            "email": u.email,
            "role": u.role,
            "headshot_url": u.headshot_url
        }


# ======= Routers =======
from ...config.path import (USER_PREFIX,
                           USER_GET_ME,
                           USER_PATCH_ME,
                           USER_PUT_ME_PASSWORD)

user_router = APIRouter(prefix=USER_PREFIX, tags=["users"])
service = UserService()

@user_router.get(USER_GET_ME)
async def read_me(request: Request):
    current_user = request.state.current_user
    return {"user": service._public_user(current_user)}


@user_router.patch(USER_PATCH_ME)
async def update_me(
    request: Request,
    body: UpdateUserProfileDTO,
    db: AsyncSession = Depends(get_session),
    
):
    current_user = request.state.current_user
    return await service.update_profile(db, current_user, body)


@user_router.put(USER_PUT_ME_PASSWORD)
async def change_password(
    request: Request,
    body: ChangePasswordRequestDTO,
    db: AsyncSession = Depends(get_session),
):
    current_user = request.state.current_user
    return await service.change_password(db, current_user, body)

@user_router.get("/token/refresh", response_model=LoginResponseDTO)
async def refresh_token(request: Request):
    """重新申請個人JWT Token"""
    current_user = request.state.current_user
    token = service._issue_token(current_user)
    return LoginResponseDTO(access_token=token)
