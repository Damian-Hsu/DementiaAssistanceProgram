# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import APIRouter, Depends, status, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from urllib.parse import parse_qs
import time
import uuid
import hashlib
import base64

from .DTO import *
from ...DataAccess.Connect import get_session
from ...security.jwt_manager import JWTManager, CameraJWTManager
from ...security.deps import get_current_api_client
from ...DataAccess.tables import api_keys, camera as camera_table
from ...DataAccess.tables.__Enumeration import CameraStatus
from ..User.service import UserService, SignupRequestDTO, LoginRequestDTO, LoginResponseDTO
from ...config.path import (AUTH_PREFIX,
                            M2M_PREFIX,
                            AUTH_POST_SIGNUP,
                            AUTH_POST_SIGNUP_ADMIN,
                            AUTH_POST_LOGIN,
                            M2M_GET_PING
                            )


auth_router = APIRouter(prefix=AUTH_PREFIX, tags=["auth"])
m2m_router = APIRouter(prefix=M2M_PREFIX, tags=["machine-to-machine"])
jwt_manager = JWTManager(expire_minutes=60)
user_service = UserService(jwt_manager)
stream_jwt = CameraJWTManager()  # 串流用短效 JWT

# ================ User Authentication API ==================

# Simple in-memory cache to avoid generating multiple tokens for the same camera in a short time

# {
# f"{token}":{
#             "payload": payload,
#             "exp": exp
#         } 
# }
_stream_token_cache = {}

def check_stream_token_cached(token: str, aud: str):
    now = time.time()

    # 快取命中但過期 → 清掉
    if token in _stream_token_cache:
        if _stream_token_cache[token]["exp"] <= now:
            del _stream_token_cache[token]
        else:
            return _stream_token_cache[token]["payload"]

    # 沒有快取 → decode
    payload = stream_jwt.decode(token, aud = aud)
    _stream_token_cache[token] = {"payload": payload, "exp": payload["exp"]}
    return payload

# ===========================================================
@auth_router.post(AUTH_POST_SIGNUP, response_model=LoginResponseDTO, status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequestDTO,
    db: AsyncSession = Depends(get_session)
):
    """
    註冊新使用者 → 建立 users.Table → 回傳 JWT
    """
    return await user_service.signup_user(db, body)

@auth_router.post(AUTH_POST_SIGNUP_ADMIN, response_model=LoginResponseDTO, status_code=status.HTTP_201_CREATED)
async def signup_admin(
    body: SignupRequestDTO,
    db: AsyncSession = Depends(get_session)
):
    return await user_service.signup_admin(db, body)

@auth_router.post(AUTH_POST_LOGIN, response_model=LoginResponseDTO)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_session)
):
    """
    登入 → 驗證帳號密碼 → 回傳 JWT
    """
    dto = LoginRequestDTO(account=form.username, password=form.password)
    return await user_service.login_user(db, dto)


# =============== Machine to Machine (M2M) API ===============

@m2m_router.get(M2M_GET_PING)
async def ping(request: Request):
    current_key: api_keys.Table = request.state.api_key
    return {"msg": "success", "owner_id": str(current_key.owner_id)}

def _make_path_from_id(cam_id: uuid.UUID, length: int = 22) -> str:
    """
    以 camera UUID 的 bytes 做 SHA-256，再 base64url，取前 length 位當公開 path。
    若你表裡沒有 path 欄位，也能 fallback 用 id.hex。
    """
    digest = hashlib.sha256(cam_id.bytes).digest()
    s = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return s[:length]


@m2m_router.post("/check-stream-pwd")
async def check_stream_pwd(req: Request):
    data = await req.json()
    proto  = data.get("protocol") # "rtsp" | "hls" | "webrtc"（MediaMTX 會送）
    action = data.get("action") # "publish" | "read"
    path   = data.get("path")
    query  = data.get("query") or ""
    token  = (parse_qs(query).get("token") or [None])[0]

    if not (proto and action and path and token):
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    # 期望的 audience ＝ 當前協議
    if proto not in ("rtsp", "hls", "webrtc"):
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    aud_expected = proto

    # 驗簽 + 驗 aud（關鍵！）
    try:
        payload = check_stream_token_cached(token, aud=aud_expected)
    except Exception:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    # 驗動作
    if payload.get("action") != action:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    # 二次確認 aud 一致（防跨用）
    if payload.get("aud") != aud_expected:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    # 驗 path ↔ cid（用同一套 _make_path_from_id）
    cid = payload.get("cid")
    if not cid:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    try:
        expected_path = _make_path_from_id(uuid.UUID(cid))
    except Exception:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    if path != expected_path:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    # （建議但可先關）驗 token_version 與 DB 一致：做一鍵失效
    # cam_ver = await db.scalar(select(camera_table.Table.token_version).where(camera_table.Table.id == uuid.UUID(cid)))
    # if cam_ver is None or int(payload.get("ver")) != int(cam_ver):
    #     return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    return Response(status_code=status.HTTP_200_OK)

