# -*- coding: utf-8 -*-
from __future__ import annotations
from uuid import UUID

from fastapi import APIRouter, Request, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...DataAccess.Connect import get_session
from ...DataAccess.tables import api_keys, users
from ...security.deps import get_current_user
from ...security.api_key_manager import APIKeyManager, APIKeyManagerConfig
from .DTO import (
    ApiKeyCreateDTO,
    ApiKeyOutDTO,
    ApiKeyPatchDTO,
    ApiKeySecretOutDTO,
)
from ...config.path import (
    ADMIN_PREFIX,
    ADMIN_POST_CREATE_KEY,
    ADMIN_GET_LIST_KEYS,
    ADMIM_PATCH_UPDATE_KEY,
    ADMIN_POST_ROTATE_KEY,
)

admin_router = APIRouter(prefix=ADMIN_PREFIX, tags=["admin"])


api_key_mgr = APIKeyManager(APIKeyManagerConfig(header_name="X-API-Key"))

def ensure_admin(u: users.Table):
    if u.role != users.Role.admin:
        raise HTTPException(status_code=403, detail="Admin only")


@admin_router.post(
    ADMIN_POST_CREATE_KEY,
    response_model=ApiKeySecretOutDTO,
    status_code=status.HTTP_201_CREATED,
)
async def create_key(
    request: Request,
    body: ApiKeyCreateDTO,
    db: AsyncSession = Depends(get_session),
):
    current_user = request.state.current_user
    ensure_admin(current_user)

    # owner 存在檢查
    res = await db.execute(select(users.Table).where(users.Table.id == body.owner_id))
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Owner user not found")

    # 透過 manager 建立（回傳 DB 記錄 + 明碼 token〈只此一次〉）
    rec, token = await api_key_mgr.create(
        db,
        name=body.name,
        owner_id=body.owner_id,
        rate_limit_per_min=body.rate_limit_per_min,
        quota_per_day=body.quota_per_day,
        active=True,
    )

    return ApiKeySecretOutDTO.model_validate(
        {**ApiKeyOutDTO.model_validate(rec).model_dump(), "token": token}
    )


@admin_router.get(ADMIN_GET_LIST_KEYS, response_model=list[ApiKeyOutDTO])
async def list_keys(
    request: Request,
    db: AsyncSession = Depends(get_session),
    owner_id: int | None = Query(None, description="依擁有者過濾（可選）"),
):
    current_user = request.state.current_user
    ensure_admin(current_user)

    # 用 manager 查列表（可選 owner_id 過濾）
    records = await api_key_mgr.list_all(db, owner_id=owner_id)
    return [ApiKeyOutDTO.model_validate(r) for r in records]


@admin_router.patch(ADMIM_PATCH_UPDATE_KEY, response_model=ApiKeyOutDTO)
async def update_key(
    request: Request,
    key_id: UUID,  # api_keys.id 是 UUIDv7
    body: ApiKeyPatchDTO,
    db: AsyncSession = Depends(get_session)
):
    current_user = request.state.current_user
    ensure_admin(current_user)

    # 抓目標 key
    rec = await api_key_mgr.get(db, key_id=key_id)

    patch = body.model_dump(exclude_unset=True)
    if "active" in patch and len(patch) == 1:
        rec = await api_key_mgr.set_active(db, key_id=key_id, active=bool(patch["active"]))
    else:
        # 這裡更新其他欄位
        for k, v in patch.items():
            setattr(rec, k, v)
        db.add(rec)
        await db.commit()
        await db.refresh(rec)

    return ApiKeyOutDTO.model_validate(rec)


@admin_router.post(
    ADMIN_POST_ROTATE_KEY,
    response_model=ApiKeySecretOutDTO,
    status_code=status.HTTP_201_CREATED,
)
async def rotate_key(
    request: Request,
    key_id: UUID,
    db: AsyncSession = Depends(get_session),
    current_user: users.Table = Depends(get_current_user),
):
    current_user = request.state.current_user
    ensure_admin(current_user)

    # 用 manager 旋轉（回新 token，舊 token 立即失效）
    rec, token = await api_key_mgr.rotate(db, key_id=key_id)

    return ApiKeySecretOutDTO.model_validate(
        {**ApiKeyOutDTO.model_validate(rec).model_dump(), "token": token}
    )
