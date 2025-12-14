# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import uuid
import hashlib
import base64
import httpx
from typing import Optional, List, Literal

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from ...DataAccess.Connect import get_session
from ...DataAccess.tables import camera as camera_table  # camera.Table
from ...DataAccess.tables import settings as settings_table
from ...DataAccess.tables import users as users_table
from ...DataAccess.tables.__Enumeration import CameraStatus, Role

from .DTO import (
    CameraCreate, CameraUpdate, CameraRead, CameraListResp, CameraStatusReq,
    OkResp, TokenVersionResp, GenerateTokenReq,
    RefreshTokenResp,PublishRTSPURLResp,StreamConnectResp,PlayWebRTCURLResp,
    StreamStatusResp
)
from ...security.jwt_manager import CameraJWTManager
from ...config.path import (CAMERA_PREFIX)
from ...config.public_domain import (
    get_public_domain,
    get_rtsp_url,
    get_webrtc_url,
)

# ====== 設定 ======
# StreamingServer 與 MediaMTX 在 docker network 內可互通的位址
# 注意：使用容器內部端口 8554，不是外部端口（內網對內網）
STREAMING_BASE = os.getenv("STREAMING_BASE", "http://streaming:30500")
STREAMING_INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "")         # 給 StreamingServer 的 X-Internal-Token
MEDIAMTX_INTERNAL_RTSP = os.getenv("MEDIAMTX_RTSP_BASE", "rtsp://mediamtx:8554")  # 內部端口 8554（內網對內網）

# 向後兼容：保留舊的環境變數名稱
RTSP_PUBLIC_HOST = os.getenv("RTSP_PUBLIC_HOST", "")
RTSP_PORT = int(os.getenv("RTSP_PORT", "8554"))  # 預設使用 Nginx 代理的端口
WEBRTC_PUBLIC_HOST = os.getenv("WEBRTC_PUBLIC_HOST", "")
WEBRTC_PORT = int(os.getenv("WEBRTC_PORT", "80"))  # 預設使用 HTTP 端口
WEBRTC_SCHEME = os.getenv("WEBRTC_SCHEME", "http")  # https 若你有 TLS


camera_router = APIRouter(prefix=CAMERA_PREFIX, tags=["camera"])

stream_jwt = CameraJWTManager()

# ====== util ======
def _make_path_from_id(cam_id: uuid.UUID, length: int = 22) -> str:
    """
    以 camera UUID 的 bytes 做 SHA-256，再 base64url，取前 length 位當公開 path。
    若你表裡沒有 path 欄位，也能 fallback 用 id.hex。
    """
    digest = hashlib.sha256(cam_id.bytes).digest()
    s = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return s[:length]


def _camera_path(cam: camera_table.Table) -> str:
    """優先使用 cam.path；沒有就用 id.hex。"""
    path = getattr(cam, "path", None)
    return path or _make_path_from_id(cam.id)


def _build_public_rtsp(cam: camera_table.Table, token: str, request: Optional[Request] = None) -> str:
    """
    構建外部 RTSP URL（給外部推流端使用，如 video2ip_camera_sim.py）
    使用公開網域配置或 Request Host header
    """
    # 獲取公開網域（優先使用環境變數，否則從 Request 獲取）
    rtsp_domain = get_public_domain("rtsp", request, default_scheme="rtsp", default_port=8554)
    path = _camera_path(cam)
    return get_rtsp_url(rtsp_domain, path, token)


def _build_internal_rtsp_for_streaming(cam: camera_table.Table, token: str) -> str:
    """
    構建內部 RTSP URL（給 StreamingServer 在 Docker 網絡內拉流用）
    使用容器內部端口 8554（不是外部端口）
    例如 "rtsp://mediamtx:8554/<path>?token=xxx"
    """
    return f"{MEDIAMTX_INTERNAL_RTSP.rstrip('/')}/{_camera_path(cam)}?token={token}"


def _build_public_webrtc(cam, webrtc_token: str, request: Optional[Request] = None) -> str:
    """構建外部 WebRTC URL，使用公開網域配置"""
    webrtc_domain = get_public_domain("webrtc", request, default_scheme=WEBRTC_SCHEME, default_port=80)
    path = _camera_path(cam)
    return get_webrtc_url(webrtc_domain, path, webrtc_token)
async def _get_camera_or_404(db: AsyncSession, id_: uuid.UUID) -> camera_table.Table:
    
    stmt = select(camera_table.Table).where(camera_table.Table.id == id_)
    res = await db.execute(stmt)
    cam = res.scalar_one_or_none()
    if not cam:
        raise HTTPException(status_code=404, detail="camera not found")
    return cam




# ====== 路由 ======
@camera_router.post("/", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
async def create_camera(request: Request, req: CameraCreate, db: AsyncSession = Depends(get_session)):
    """
    新增相機：預設 active、token_version=1。
    若模型上存在 rtsp_path 欄位，會在取得 id 後自動填入。
    """
    current_user = request.state.current_user

    # 權限：一般使用者只能建立自己的相機；管理員可指定 user_id
    if current_user.role != Role.admin:
        target_user_id = int(current_user.id)
    else:
        if req.user_id is None:
            raise HTTPException(status_code=400, detail="user_id is required for admin")
        target_user_id = int(req.user_id)

    # 檢查使用者是否存在（避免 FK violation 500）
    ures = await db.execute(select(users_table.Table.id).where(users_table.Table.id == target_user_id))
    if ures.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"使用者不存在：user_id={target_user_id}")

    cam = camera_table.Table(
        user_id=target_user_id,
        name=req.name,
        status=CameraStatus.active,
        # allow_ip=req.allow_ip,
        max_publishers=req.max_publishers or 1,
    )
    db.add(cam)
    # 先 flush 取得 id
    await db.flush()

    # 如果表有 rtsp_path 欄位，且目前為空，就幫你產生
    if hasattr(cam, "path"):
        cur = getattr(cam, "path", None)
        if not cur:
            setattr(cam, "path", _make_path_from_id(cam.id))
            db.add(cam)

    await db.commit()
    await db.refresh(cam)
    return cam  # Pydantic CameraRead(from_attributes=True) 會自動轉


@camera_router.patch("/{id}", response_model=OkResp)
async def update_camera(request: Request,
                        id: uuid.UUID,
                        req: CameraUpdate,
                        db: AsyncSession = Depends(get_session)):
    current_user = request.state.current_user
    cam = await _get_camera_or_404(db, id)
    # 只有管理員或擁有者可以修改所有相機，但一般使用者只能改自己的
    if current_user.role != Role.admin and current_user.id != cam.user_id:
        raise HTTPException(status_code=403, detail="沒有權限修改此相機")
    patch = req.model_dump(exclude_unset=True)
    for k, v in patch.items():
        setattr(cam, k, v)
    db.add(cam)
    await db.commit()
    return OkResp()


@camera_router.delete("/{id}", response_model=OkResp)
async def delete_camera(request: Request,
                        id: uuid.UUID,
                        db: AsyncSession = Depends(get_session)):
    """
    Demo：做邏輯刪除（status=deleted）。
    如果你真的要物理刪除，改成 await db.delete(cam) + commit 即可。
    """
    cam = await _get_camera_or_404(db, id)
    current_user = request.state.current_user
    # 只有管理員或擁有者可以修改所有相機，但一般使用者只能改自己的
    if current_user.role != Role.admin and current_user.id != cam.user_id:
        raise HTTPException(status_code=403, detail="沒有權限修改此相機")
    cam.status = CameraStatus.deleted
    db.add(cam)
    await db.commit()
    return OkResp()


@camera_router.get("/", response_model=CameraListResp)
async def list_cameras(
    request: Request,
    user_id: Optional[int] = Query(None),
    status: Optional[CameraStatus] = Query(None),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
):  
    """列出某使用者的相機（管理員可看所有人，一般使用者只能看自己的）。"""
    current_user = request.state.current_user
    # 若未提供 user_id：一般使用者預設看自己；管理員預設看自己（避免一次列出全站）
    target_user_id = int(user_id) if user_id is not None else int(current_user.id)

    if current_user.role != Role.admin and int(current_user.id) != target_user_id:
        raise HTTPException(status_code=403, detail="沒有權限查看此使用者的相機")

    conds = [camera_table.Table.user_id == target_user_id]
    if status:
        conds.append(camera_table.Table.status == status)
    if q:
        conds.append(camera_table.Table.name.ilike(f"%{q}%"))

    # 動態選擇排序欄位
    order_col = getattr(camera_table.Table, "created_at", None) or camera_table.Table.id

    stmt_items = (
        select(camera_table.Table)
        .where(and_(*conds))
        .order_by(order_col.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    stmt_total = select(func.count()).select_from(
        select(camera_table.Table).where(and_(*conds)).subquery()
    )

    rows = (await db.execute(stmt_items)).scalars().all()
    total = (await db.execute(stmt_total)).scalar_one()
    return CameraListResp(items=rows, total=total)


@camera_router.get("/{id}", response_model=CameraRead)
async def get_camera(request: Request,
                     id: uuid.UUID,
                     db: AsyncSession = Depends(get_session)):
    """取得單一相機資訊（管理員可看所有人，一般使用者只能看自己的）。"""
    current_user = request.state.current_user
    if current_user.role != Role.admin:
        # 一般使用者只能看自己的相機
        stmt = select(camera_table.Table).where(
            and_(
                camera_table.Table.id == id,
                camera_table.Table.user_id == current_user.id
            )
        )
        res = await db.execute(stmt)
        cam = res.scalar_one_or_none()
        if not cam:
            raise HTTPException(status_code=404, detail="相機不存在或沒有權限")
    else:
        cam = await _get_camera_or_404(db, id)

    return cam


@camera_router.patch("/{id}/status", response_model=OkResp)
async def set_status(request: Request,
                     id: uuid.UUID,
                     req: CameraStatusReq,
                     db: AsyncSession = Depends(get_session)):
    """
    修改相機狀態（active / inactive / deleted）。
    只有管理員或擁有者可以修改所有相機，但一般使用者只能改自己的。
    """
    current_user = request.state.current_user
    cam = await _get_camera_or_404(db, id)
    if current_user.role != Role.admin and current_user.id != cam.user_id:
        raise HTTPException(status_code=403, detail="沒有權限修改此相機")
    cam.status = CameraStatus(req.status)
    db.add(cam)
    await db.commit()
    return OkResp()


@camera_router.post("/{id}/token/version-rotate", response_model=TokenVersionResp)
async def rotate_token_version(request: Request,
                               id: uuid.UUID,
                               db: AsyncSession = Depends(get_session)):
    """
    一鍵失效所有舊 token（這台相機）：token_version += 1
    """
    current_user = request.state.current_user
    if current_user.role != Role.admin:
        # 一般使用者只能改自己的相機
        stmt = select(camera_table.Table).where(
            and_(
                camera_table.Table.id == id,
                camera_table.Table.user_id == current_user.id
            )
        )
        res = await db.execute(stmt)
        cam = res.scalar_one_or_none()
        if not cam:
            raise HTTPException(status_code=404, detail="相機不存在或沒有權限")
    else:
        cam = await _get_camera_or_404(db, id)

    cam.token_version = int(cam.token_version) + 1
    db.add(cam)
    await db.commit()
    await db.refresh(cam)
    return TokenVersionResp(token_version=cam.token_version)


@camera_router.post("/{id}/stream/connect", response_model=StreamConnectResp)
async def connect_stream(
    id: uuid.UUID,
    req: GenerateTokenReq,
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """
    建立 RTSP 推流：
    1) 簽 publisher token → 給客戶端推流。
    2) 簽 player token → StreamingServer 拉流（內部用）。
    3) 呼叫 /streams/start 開錄。
    """
    cam = await _get_camera_or_404(db, id)
    current_user = request.state.current_user
    if current_user.role != Role.admin and current_user.id != cam.user_id:
        raise HTTPException(status_code=403, detail="沒有權限操作此相機")
    if cam.status != CameraStatus.active:
        raise HTTPException(status_code=403, detail=f"camera status={cam.status} not allowed")
    _ttl = max(req.ttl or 10800, 300)  # RTSP 推流：預設 10800 秒，最少 300 秒
    # internal token (StreamingServer 拉流用)
    internal_rtsp_token = stream_jwt.issue(
        camera_id=str(cam.id),
        action="read",
        token_version=int(cam.token_version),
        ttl=_ttl,  # 最少 60 秒
        aud="rtsp"
    )
    internal_play_url = _build_internal_rtsp_for_streaming(cam, internal_rtsp_token)

    # 呼叫 StreamingServer 開錄
    # 影片切片長度：優先用 request 指定；否則讀取系統設定（管理員可在管理員設定頁調整）；最後 fallback 30
    segment_seconds = getattr(req, "segment_seconds", None)
    if not segment_seconds:
        try:
            import json
            stmt = select(settings_table.Table).where(settings_table.Table.key == "video_segment_seconds")
            result = await db.execute(stmt)
            setting = result.scalar_one_or_none()
            if setting:
                value = json.loads(setting.value)
                if isinstance(value, dict) and value.get("segment_seconds") is not None:
                    segment_seconds = int(value["segment_seconds"])
                elif isinstance(value, (int, float, str)):
                    segment_seconds = int(value)
        except Exception:
            segment_seconds = None
    if not segment_seconds:
        segment_seconds = 30

    payload = {
        "user_id": str(cam.user_id),
        "camera_id": str(cam.id),
        "rtsp_url": internal_play_url,
        "segment_seconds": int(segment_seconds),
        "align_first_cut": bool(getattr(req, "align_first_cut", True)),
        "startup_deadline_ts": _ttl
    }
    headers = {"X-Internal-Token": STREAMING_INTERNAL_TOKEN} if STREAMING_INTERNAL_TOKEN else {}
    start_url = f"{STREAMING_BASE.rstrip('/')}/streams/start"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(start_url, json=payload, headers=headers)
        if resp.status_code not in (200, 201, 202, 409):
            raise HTTPException(
                status_code=502,
                detail=f"streaming/start failed: {resp.status_code} {resp.text}",
            )
    
    return StreamConnectResp(
        ttl=_ttl,
        info=resp.json() if resp.status_code == 200 else None
    )

@camera_router.post("/{id}/stream/stop", response_model=OkResp)
async def stop_stream(
    id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """
    停止錄影（StreamingServer 停拉流與切片）。
    """
    cam = await _get_camera_or_404(db, id)
    current_user = request.state.current_user
    if current_user.role != Role.admin and current_user.id != cam.user_id:
        raise HTTPException(status_code=403, detail="沒有權限操作此相機")
    if cam.status != CameraStatus.active:
        raise HTTPException(status_code=403, detail=f"camera status={cam.status} not allowed")

    headers = {"X-Internal-Token": STREAMING_INTERNAL_TOKEN} if STREAMING_INTERNAL_TOKEN else {}
    stop_url = f"{STREAMING_BASE.rstrip('/')}/streams/stop"
    payload = {
        "user_id": str(cam.user_id),
        "camera_id": str(cam.id)
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(stop_url, json=payload, headers=headers)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"streaming/stop failed: {resp.status_code} {resp.text}",
            )
    return OkResp()

@camera_router.get("/{id}/publish_rtsp_url")
async def get_publish_rtsp_url(
    id: uuid.UUID,
    request: Request,
    ttl: Optional[int] = Query(10800, ge=300, le=21600),
    db: AsyncSession = Depends(get_session)
):
    """
    發 RTSP 推流用的 JWT，回傳帶 token 的 URL。
    """
    cam = await _get_camera_or_404(db, id)
    current_user = request.state.current_user
    if current_user.role != Role.admin and current_user.id != cam.user_id:
        raise HTTPException(status_code=403, detail="沒有權限操作此相機")
    if cam.status != CameraStatus.active:
        raise HTTPException(status_code=403, detail=f"camera status={cam.status} not allowed")

    publish_rtsp_token = stream_jwt.issue(
        camera_id=str(cam.id),
        action="publish",
        token_version=int(cam.token_version),
        ttl=ttl,
        aud="rtsp"
    )
    public_publish_url = _build_public_rtsp(cam, publish_rtsp_token, request)

    now = int(datetime.now(timezone.utc).timestamp())
    return PublishRTSPURLResp(
        publish_rtsp_url=public_publish_url,
        ttl=ttl,
        expires_at=now + ttl,
    )

@camera_router.get("/{id}/stream/status", response_model=StreamStatusResp)
async def get_stream_status(
    id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_session)
):
    """
    查詢鏡頭的串流狀態。
    """
    cam = await _get_camera_or_404(db, id)
    current_user = request.state.current_user
    if current_user.role != Role.admin and current_user.id != cam.user_id:
        raise HTTPException(status_code=403, detail="沒有權限操作此相機")
    
    # 查詢 StreamingServer 的串流狀態
    headers = {"X-Internal-Token": STREAMING_INTERNAL_TOKEN} if STREAMING_INTERNAL_TOKEN else {}
    streams_url = f"{STREAMING_BASE.rstrip('/')}/streams"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(streams_url, headers=headers)
            if resp.status_code == 200:
                streams = resp.json()
                # 查找匹配的串流
                for stream in streams:
                    if stream.get("camera_id") == str(cam.id) and stream.get("user_id") == str(cam.user_id):
                        status = stream.get("status", "stopped")
                        error_message = stream.get("error_message")
                        return StreamStatusResp(
                            is_streaming=(status in ["starting", "running", "reconnecting"]),
                            status=status,
                            stream_info=stream,
                            error_message=error_message
                        )
    except Exception as e:
        # 如果查詢失敗，返回未串流狀態
        print(f"[Stream Status] Failed to query streaming server: {e}")
    
    return StreamStatusResp(
        is_streaming=False,
        status="stopped",
        stream_info=None,
        error_message=None
    )

@camera_router.get("/{id}/play-webrtc-url", response_model=PlayWebRTCURLResp)
async def get_play_webrtc_url(
    id: uuid.UUID,
    request: Request,
    ttl: Optional[int] = Query(180, ge=30, le=10800),
    db: AsyncSession = Depends(get_session)
):
    """
    發 WebRTC 播放用的 JWT，回傳帶 token 的 URL。
    """
    cam = await _get_camera_or_404(db, id)
    current_user = request.state.current_user
    if current_user.role != Role.admin and current_user.id != cam.user_id:
        raise HTTPException(status_code=403, detail="沒有權限操作此相機")
    if cam.status != CameraStatus.active:
        raise HTTPException(status_code=403, detail=f"camera status={cam.status} not allowed")

    webrtc_token_public = stream_jwt.issue(
        camera_id=str(cam.id),
        action="read",
        token_version=int(cam.token_version),
        ttl=ttl,
        aud="webrtc"
    )
    public_play_webrtc_url = _build_public_webrtc(cam, webrtc_token_public, request)

    now = int(datetime.now(timezone.utc).timestamp())
    return PlayWebRTCURLResp(
        play_webrtc_url=public_play_webrtc_url,
        ttl=ttl,
        expires_at=now + ttl
    )

@camera_router.get("/{id}/token/refresh/{audience}")
async def refresh_token(
    id: uuid.UUID,
    request: Request, # 這裡面有 current_user
    audience: Literal["rtsp", "webrtc"] = Path(..., description="指定要重新簽發的 token 用途"),
    token : str = Query(description="還在有效期內的舊 token"),
    db: AsyncSession = Depends(get_session)
):
    """
    重新簽發串流，只負責延長有效期（refresh token）。
    需要提供還在有效期內的舊 token，並且會驗證 token 的有效性與欄位。
    """
    cam = await _get_camera_or_404(db, id)
    current_user = request.state.current_user
    if current_user.role != Role.admin and current_user.id != cam.user_id:
        raise HTTPException(status_code=403, detail="沒有權限操作此相機")
    if cam.status != CameraStatus.active:
        raise HTTPException(status_code=403, detail=f"camera status={cam.status} not allowed")

    # 驗證舊 token 
    try:
        payload = stream_jwt.decode(token, aud=audience)  # 這裡會驗 exp/iat/aud/ver
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"invalid token: {str(e)}")
    # 基本欄位比對
    if payload.get("cid") != str(cam.id):
        raise HTTPException(status_code=401, detail="token cid mismatch")
    
    if payload.get("ver") != int(cam.token_version):
        raise HTTPException(status_code=401, detail="token version mismatch")
    
    action = payload.get("action")
    if action not in ("publish", "read"):
        raise HTTPException(status_code=401, detail="token action invalid")

    # 簽發新 token
    token = stream_jwt.issue(
        camera_id=str(cam.id),
        action=action,
        token_version=int(cam.token_version),
        ttl=payload.get("ttl"),
        aud=audience
    )
    now = int(datetime.now(timezone.utc).timestamp())
    ttl = payload.get("ttl")
    
    return RefreshTokenResp(
        audience=audience,
        action=action,
        token=token,
        ttl=ttl,
        expires_at=now + ttl,
    )
