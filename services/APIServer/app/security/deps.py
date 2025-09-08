# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends, HTTPException, status, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import time

from ..DataAccess.Connect import get_session
from ..DataAccess.tables import users, api_keys
from .jwt_manager import JWTManager
from .api_key_manager import APIKeyManager, APIKeyManagerConfig
from ..config.path import (API_ROOT,
                            AUTH_PREFIX,
                            AUTH_POST_LOGIN)

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{API_ROOT}{AUTH_PREFIX}{AUTH_POST_LOGIN}")
_jwt_manager = JWTManager()
_current_user_cache = {}

def check_user_token_cached(token: str):
    now = time.time()

    # 快取命中但過期 → 清掉
    if token in _current_user_cache:
        if _current_user_cache[token]["exp"] <= now:
            del _current_user_cache[token]
        else:
            return _current_user_cache[token]["payload"]

    # 沒有快取 → decode
    payload = _jwt_manager.decode_token(token)
    _current_user_cache[token] = {"payload": payload, "exp": payload["exp"]}
    return payload

async def get_current_user(
    request: Request,
    token: str = Depends(_oauth2_scheme),
    db: AsyncSession = Depends(get_session),
) -> users.Table:
    payload = check_user_token_cached(token)
    sub = payload.get("sub")
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="權杖缺少主體（sub）",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="權杖的 sub 格式無效（需為整數）",
            headers={"WWW-Authenticate": "Bearer"},
        )

    stmt = select(users.Table).where(users.Table.id == user_id)
    result = await db.execute(stmt)
    user_obj: users.Table | None = result.scalar_one_or_none()
    if user_obj is None:
        # 建議：安全起見可改成 401，避免洩漏存在性
        raise HTTPException(status_code=404, detail="使用者不存在")

    if not bool(getattr(user_obj, "active", False)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="帳號未啟用")

    # 關鍵：存到 request.state，方便 handler 直接取
    request.state.current_user = user_obj
    return user_obj


async def get_current_user_schema(
    user: users.Table = Depends(get_current_user),
) -> users.Schema:
    """
    可選：若某些路由想直接回傳 Pydantic Schema。
    """
    return users.Schema(
        id=user.id,
        account=user.account,
        name=user.name,
        role=user.role,
        gender=user.gender,
        dementia_level=user.dementia_level,
        birthday=user.birthday,
        phone=user.phone,
        email=user.email,
        password_hash=user.password_hash,  # 不想外傳就移除
    )


async def require_admin(user: users.Table = Depends(get_current_user)) -> users.Table:
    """
    僅允許 admin 使用的依賴；非 admin 直接 403。
    依你的 Enum/實際值調整比較方式。
    """
    role_val = getattr(user, "role", None)
    if role_val != users.Role.admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


_api_key_manager = APIKeyManager(APIKeyManagerConfig(header_name="X-API-Key"))
get_current_api_client = _api_key_manager.require()   # 不做 scope 檢查
