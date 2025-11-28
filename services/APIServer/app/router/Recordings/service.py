# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import uuid
from typing import Optional, List, Tuple
from datetime import date, datetime, time, timedelta, timezone

import boto3
from botocore.config import Config

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, delete, exists

from ...DataAccess.Connect import get_session
from ...DataAccess.tables import recordings as recordings_table  # recordings_table.Table
from ...DataAccess.tables import events as events_table          # events_table.Table
from ...router.User.service import UserService

from .DTO import (
    RecordingRead, RecordingListResp, RecordingUrlResp, OkResp, EventRead
)

# ------------------------------------------------------------
# Router
# ------------------------------------------------------------
recordings_router = APIRouter(prefix="/recordings", tags=["recordings"])

# ------------------------------------------------------------
# User Service 實例
# ------------------------------------------------------------
user_service = UserService()

# ------------------------------------------------------------
# S3/MinIO：你可把下列兩函式改成你「已驗證成功」的封裝
# ------------------------------------------------------------
# 內部使用的 endpoint（Docker 網絡內）
INTERNAL_MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")

# 外部可達的 endpoint（瀏覽器訪問）
# 注意：docker-compose.yml 中 MinIO 的端口映射是 30300:9000
PUBLIC_MINIO_ENDPOINT = os.getenv("PUBLIC_MINIO_ENDPOINT", "http://localhost:30300")

# S3 客戶端使用內部 endpoint（服務器端訪問）
S3_ENDPOINT   = INTERNAL_MINIO_ENDPOINT
S3_ACCESS_KEY = os.getenv("MINIO_ROOT_USER",  os.getenv("S3_ACCESS_KEY", "minioadmin"))
S3_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", os.getenv("S3_SECRET_KEY", "minioadmin"))
S3_REGION     = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET     = os.getenv("MINIO_BUCKET", "media-bucket")

# 一律用 path-style，避免變成 videos.minio:30300 這種外部解析不到的子網域
_s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    region_name=S3_REGION,
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"}   # ← 關鍵
    ),
)

def _normalize_key(key: str) -> str:
    """
    正規化 S3 key，確保格式正確且不包含不支援的字符。
    
    處理的情況：
    1. s3://bucket/key 格式
    2. bucket/key 格式
    3. 直接 key 格式
    4. 清理多餘的斜線和空格
    """
    if not key:
        raise ValueError("S3 key cannot be empty")
    
    # 1) 去掉 s3://bucket/... 前綴
    if key.startswith("s3://"):
        without_scheme = key.split("://", 1)[1]
        # 去掉前面的 bucket 名（不管它是 videos 還是 media-bucket）
        if "/" in without_scheme:
            without_scheme = without_scheme.split("/", 1)[1]
        key = without_scheme

    # 2) 若 key 仍以任一 bucket 名開頭（videos/ 或 media-bucket/），去掉之
    for b in (os.getenv("S3_BUCKET", ""), "videos", "media-bucket"):
        if b and key.startswith(f"{b}/"):
            key = key[len(b) + 1 :]
            break

    # 3) 清理多餘的斜線和空格，確保格式正確
    # 移除開頭和結尾的斜線
    key = key.strip("/")
    # 將多個連續斜線替換為單個斜線
    while "//" in key:
        key = key.replace("//", "/")
    # 移除開頭和結尾的空格
    key = key.strip()
    
    # 4) 驗證 key 不為空（這裡 key 已經被處理過，如果為空說明原始 key 有問題）
    if not key:
        raise ValueError("Normalized S3 key is empty after processing")
    
    return key

def _presign_get(key: str, ttl: int, *, disposition: Optional[str], filename: Optional[str], content_type: Optional[str] = None) -> str:
    key = _normalize_key(key)  # 如果你有這支，保留
    params = {"Bucket": S3_BUCKET, "Key": key}

    # 根據文件類型設置 ContentType（縮圖為 image/jpeg，影片為 video/mp4）
    if content_type:
        params["ResponseContentType"] = content_type
    else:
        # 根據 key 的副檔名判斷類型
        if key.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
            params["ResponseContentType"] = "image/jpeg"
        else:
            params["ResponseContentType"] = "video/mp4"

    # 預設 inline；若你從 query 傳進來就尊重使用者
    disp = disposition or "inline"
    safe_name = filename or key.rsplit("/", 1)[-1]
    params["ResponseContentDisposition"] = f'{disp}; filename="{safe_name}"'

    # 如果內部和外部的 endpoint 不同，需要創建外部客戶端來生成預簽名 URL
    # 因為預簽名 URL 的簽名是基於 host 的，不能直接替換 host
    if INTERNAL_MINIO_ENDPOINT != PUBLIC_MINIO_ENDPOINT:
        # 創建外部 S3 客戶端（用於生成瀏覽器可訪問的預簽名 URL）
        _s3_public = boto3.client(
            "s3",
            endpoint_url=PUBLIC_MINIO_ENDPOINT,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            region_name=S3_REGION,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"}
            ),
        )
        presigned_url = _s3_public.generate_presigned_url("get_object", Params=params, ExpiresIn=int(ttl))
    else:
        # 如果內部外部相同，直接使用內部客戶端
        presigned_url = _s3.generate_presigned_url("get_object", Params=params, ExpiresIn=int(ttl))
    
    return presigned_url

def _delete_object(key: str) -> None:
    """刪除物件；不存在也視為成功（S3 的語意即是冪等）。"""
    # 正規化 key，確保格式正確
    normalized_key = _normalize_key(key)
    try:
        _s3.delete_object(Bucket=S3_BUCKET, Key=normalized_key)
    except Exception as e:
        # 記錄錯誤詳情以便調試
        print(f"[Delete Object Error] Original key: {key}")
        print(f"[Delete Object Error] Normalized key: {normalized_key}")
        print(f"[Delete Object Error] Error: {e}")
        raise

# ------------------------------------------------------------
# Utils
# ------------------------------------------------------------
def _date_to_utc_range(d: date, user_timezone: str = "Asia/Taipei") -> Tuple[datetime, datetime]:
    """把 local ISO date 轉為該日 UTC [00:00, 次日00:00)。使用使用者時區進行轉換。"""
    import pytz
    
    # 獲取使用者時區
    user_tz = pytz.timezone(user_timezone)
    
    # 在使用者時區中創建日期時間
    local_start = user_tz.localize(datetime.combine(d, time.min))
    local_end = user_tz.localize(datetime.combine(d, time.max))
    
    # 轉換為 UTC
    utc_start = local_start.astimezone(timezone.utc)
    utc_end = local_end.astimezone(timezone.utc)
    
    return utc_start, utc_end

def _build_time_preds(start_d: Optional[date], end_d: Optional[date], col, user_timezone: str = "Asia/Taipei"):
    preds = []
    if start_d and end_d:
        s0, _ = _date_to_utc_range(start_d, user_timezone)
        e0, _ = _date_to_utc_range(end_d, user_timezone)
        preds.extend([col >= s0, col < (e0 + timedelta(days=1))])
    elif start_d:
        s0, e0 = _date_to_utc_range(start_d, user_timezone)
        preds.extend([col >= s0, col < e0])
    elif end_d:
        s0, e0 = _date_to_utc_range(end_d, user_timezone)
        preds.extend([col >= s0, col < e0])
    return preds

def _parse_sort(sort: Optional[str], allowed: dict, default_key: str):
    """
    sort 格式：
      - "field"（預設 desc）
      - "-field" / "+field"
      - "field:asc" / "field:desc"
    """
    if not sort:
        return allowed[default_key].desc()
    raw = sort.strip().lower()
    desc = True
    field = raw
    if ":" in raw:
        field, dir_ = raw.split(":", 1)
        desc = (dir_.strip() == "desc")
    elif raw.startswith("-"):
        field = raw[1:]; desc = True
    elif raw.startswith("+"):
        field = raw[1:]; desc = False
    col = allowed.get(field, allowed[default_key])
    return col.desc() if desc else col.asc()

def _events_keyword_exists_condition(keywords: Optional[str], sr: Optional[List[str]]):
    """
    在 recordings 上用 exists 子查詢過濾：關鍵字比對 *事件* 欄位。
    sr：允許 action / scene / summary / objects
    objects 以「元素等值包含」查（需要子字串請改 unnest ILIKE）。
    """
    if not keywords:
        return None
    kw = keywords.strip()
    if not kw:
        return None
    scope = set(sr or []) & {"action", "scene", "summary", "objects"}
    if not scope:
        scope = {"summary"}  # 你的規格：預設查 events.summary
    like = f"%{kw}%"
    preds = []
    from ...DataAccess.tables import events as _ev
    if "action" in scope:   preds.append(_ev.Table.action.ilike(like))
    if "scene" in scope:    preds.append(_ev.Table.scene.ilike(like))
    if "summary" in scope:  preds.append(_ev.Table.summary.ilike(like))
    if "objects" in scope:  preds.append(_ev.Table.objects.contains([kw]))
    if not preds:
        return None
    subq = select(_ev.Table.id).where(and_(_ev.Table.recording_id == recordings_table.Table.id, or_(*preds)))
    return exists(subq)

# ------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------

@recordings_router.get("/{recording_id}", response_model=RecordingUrlResp)
async def get_recording_url(
    request: Request,  # 🔧 修復：添加權限檢查
    recording_id: uuid.UUID = Path(..., description="錄影片段 ID"),
    ttl: int = Query(900, ge=30, le=7*24*3600, description="URL 有效秒數（預設 900，最大 7 天）"),
    disposition: Optional[str] = Query(None, regex="^(inline|attachment)$", description="瀏覽器呈現方式：inline 或 attachment"),
    filename: Optional[str] = Query(None, description="下載檔名；未提供則使用 s3_key 的檔名"),
    db: AsyncSession = Depends(get_session),
):
    """
    取得影片的 **Pre-signed GET URL**（可直接播放/下載；支援 HTTP Range）。

    **Query 參數**
    - `ttl`: `int`，連結有效秒數，預設 `900`，範圍 `30..604800`
    - `disposition`: `inline | attachment`，控制瀏覽器顯示或下載
    - `filename`: `str | None`，下載檔名（未提供則取 `s3_key` 尾段）

    **呼叫範例**
    - 直接播放（5 分鐘）：  
      `GET /recordings/{id}?ttl=300&disposition=inline`
    - 下載並指定檔名（30 分鐘）：  
      `GET /recordings/{id}?ttl=1800&disposition=attachment&filename=myvideo.mp4`
    
    **注意**：此端點僅回傳影片 URL，不包含 recording 詳細資訊。
    """
    # 🔧 修復：添加權限檢查
    current_user = request.state.current_user
    from ...DataAccess.tables.__Enumeration import Role
    
    stmt = select(recordings_table.Table).where(recordings_table.Table.id == recording_id)
    rec = (await db.execute(stmt)).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="recording not found")
    
    # 非管理員只能訪問自己的錄影
    if current_user.role != Role.admin and rec.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="沒有權限訪問此錄影")

    # 根據 type 參數決定使用哪個 s3_key
    if type == "thumbnail" and rec.thumbnail_s3_key:
        s3_key = rec.thumbnail_s3_key
        url = _presign_get(s3_key, ttl, disposition=disposition, filename=filename, content_type="image/jpeg")
        now = int(datetime.now(timezone.utc).timestamp())
        return RecordingUrlResp(url=url, ttl=ttl, expires_at=now + ttl)
    else:
        s3_key = rec.s3_key
        url = _presign_get(s3_key, ttl, disposition=disposition, filename=filename, content_type="video/mp4")
        now = int(datetime.now(timezone.utc).timestamp())
        # 如果有縮圖，同時返回縮圖 URL
        thumbnail_url = None
        if rec.thumbnail_s3_key:
            thumbnail_url = _presign_get(rec.thumbnail_s3_key, ttl, disposition="inline", content_type="image/jpeg")
        return RecordingUrlResp(url=url, ttl=ttl, expires_at=now + ttl, thumbnail_url=thumbnail_url)


@recordings_router.delete("/{recording_id}", response_model=OkResp, status_code=status.HTTP_200_OK)
async def delete_recording(
    request: Request,  # 🔧 修復：添加權限檢查
    recording_id: uuid.UUID = Path(..., description="錄影片段 ID"),
    db: AsyncSession = Depends(get_session),
):
    """
    **硬刪除** 錄影片段：刪 S3 物件 + 刪 DB 紀錄。  
    若 `events.recording_id` 沒有 `ON DELETE CASCADE`，此處會一併刪除關聯事件。

    **步驟**
    1. 讀取 DB 取得 `s3_key`  
    2. 刪除 S3 物件（冪等）  
    3. 刪除關聯事件（若未啟用級聯）  
    4. 刪除錄影紀錄

    **呼叫範例**
    - `DELETE /recordings/{id}`
    """
    # 🔧 修復：添加權限檢查
    current_user = request.state.current_user
    from ...DataAccess.tables.__Enumeration import Role
    
    stmt = select(recordings_table.Table).where(recordings_table.Table.id == recording_id)
    rec = (await db.execute(stmt)).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="recording not found")
    
    # 非管理員只能刪除自己的錄影
    if current_user.role != Role.admin and rec.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="沒有權限刪除此錄影")

    try:
        _delete_object(rec.s3_key)
    except ValueError as e:
        # key 正規化錯誤
        raise HTTPException(status_code=400, detail=f"Invalid S3 key format: {e}")
    except Exception as e:
        # 其他 S3 錯誤
        error_msg = str(e)
        # 提取更友好的錯誤訊息
        if "XMinioInvalidObjectName" in error_msg or "unsupported characters" in error_msg.lower():
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid S3 object name: {rec.s3_key}. The object name contains unsupported characters."
            )
        raise HTTPException(status_code=502, detail=f"S3 delete failed: {error_msg}")

    # 若你的 DB 已設 CASCADE，可移除以下兩段 delete
    await db.execute(delete(events_table.Table).where(events_table.Table.recording_id == recording_id))
    await db.execute(delete(recordings_table.Table).where(recordings_table.Table.id == recording_id))
    await db.commit()
    return OkResp()


@recordings_router.get("/", response_model=RecordingListResp)
async def list_recordings(
    request: Request,  # 🔧 修復：添加 request 參數以獲取 current_user
    user_id: Optional[int] = Query(default=None, description="指定使用者 ID（僅管理員可用）"),
    keywords: Optional[str] = Query(None, description="在 *事件* 欄位內搜尋的關鍵字（預設比對 `summary`）"),
    sr: Optional[List[str]] = Query(None, description="查詢範圍，多值：`?sr=action&sr=scene&sr=objects`；預設只查 `summary`"),
    start_time: Optional[date] = Query(None, description="ISO local date；會轉為整日 UTC 開始"),
    end_time: Optional[date] = Query(None, description="ISO local date；若與 start_time 同給則形成區間"),
    sort: Optional[str] = Query(None, description="排序欄位：`start_time|created_at|duration|size_bytes|id`；可 `:asc|:desc` 或 `-field`"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
):
    """
    查詢 **影片列表**（事件關鍵字、時間、排序、分頁）。

    **Query 參數**
    - `keywords`: `str | None`，搜尋 *事件* 欄位（預設 `summary`）
    - `sr`: `List[str] | None`，範圍 `action|scene|summary|objects`
    - `start_time`, `end_time`: `date | None`，轉換為整日 UTC 範圍
    - `sort`: 允許 `start_time|created_at|duration|size_bytes|id`，可 `:asc|:desc` 或 `-field`
    - `page`, `size`: 分頁

    **呼叫範例**
    - 找出 2025-03-01 當天包含「喝水」事件摘要的影片：  
      `GET /recordings?keywords=喝水&start_time=2025-03-01&sort=-start_time&page=1&size=20`
    - 指定查詢範圍為 `action` 與 `objects`：  
      `GET /recordings?keywords=drinking&sr=action&sr=objects`
    """
    # 🔧 修復：添加用戶權限檢查（非管理員只能查看自己的錄影）
    current_user = request.state.current_user
    from ...DataAccess.tables.__Enumeration import Role
    
    # 獲取使用者時區
    user_timezone = user_service.get_user_timezone(current_user)
    
    conds = []
    
    # 權限控制：使用者 ID 過濾
    if current_user.role == Role.admin:
        # 管理員：可以使用手動輸入的 user_id，如果沒有則使用自己的 ID
        target_user_id = user_id if user_id is not None else current_user.id
        conds.append(recordings_table.Table.user_id == target_user_id)
    else:
        # 一般使用者：只能查詢自己的影片，忽略手動輸入的 user_id
        conds.append(recordings_table.Table.user_id == current_user.id)
    
    conds += _build_time_preds(start_time, end_time, recordings_table.Table.start_time, user_timezone)

    exists_pred = _events_keyword_exists_condition(keywords, sr)
    if exists_pred is not None:
        conds.append(exists_pred)

    allowed = {
        "start_time": recordings_table.Table.start_time,
        "created_at": getattr(recordings_table.Table, "created_at", recordings_table.Table.start_time),
        "duration": recordings_table.Table.duration,
        "size_bytes": recordings_table.Table.size_bytes,
        "id": recordings_table.Table.id,
    }
    order_by = _parse_sort(sort, allowed, default_key="start_time")

    base_sel = select(recordings_table.Table)
    if conds:
        base_sel = base_sel.where(and_(*conds))

    stmt_items = base_sel.order_by(order_by).offset((page - 1) * size).limit(size)
    stmt_total = select(func.count()).select_from(base_sel.subquery())

    rows = (await db.execute(stmt_items)).scalars().all()
    total = (await db.execute(stmt_total)).scalar_one()
    
    # 🔧 修復：為每個 recording 填充 summary（從第一個 event）並轉換時間到使用者時區
    import pytz
    user_tz = pytz.timezone(user_timezone)
    items_with_summary = []
    for rec in rows:
        # 查詢該 recording 的第一個 event 的 summary
        stmt_event = (
            select(events_table.Table.summary)
            .where(events_table.Table.recording_id == rec.id)
            .order_by(events_table.Table.start_time.asc())
            .limit(1)
        )
        first_summary = (await db.execute(stmt_event)).scalar_one_or_none()
        
        # 轉換時間到使用者時區
        start_time_user = rec.start_time
        if start_time_user:
            if start_time_user.tzinfo is None:
                start_time_user = start_time_user.replace(tzinfo=timezone.utc)
            start_time_user = start_time_user.astimezone(user_tz)
        
        end_time_user = rec.end_time
        if end_time_user:
            if end_time_user.tzinfo is None:
                end_time_user = end_time_user.replace(tzinfo=timezone.utc)
            end_time_user = end_time_user.astimezone(user_tz)
        
        created_at_user = getattr(rec, "created_at", None)
        if created_at_user:
            if created_at_user.tzinfo is None:
                created_at_user = created_at_user.replace(tzinfo=timezone.utc)
            created_at_user = created_at_user.astimezone(user_tz)
        
        updated_at_user = getattr(rec, "updated_at", None)
        if updated_at_user:
            if updated_at_user.tzinfo is None:
                updated_at_user = updated_at_user.replace(tzinfo=timezone.utc)
            updated_at_user = updated_at_user.astimezone(user_tz)
        
        # 將 ORM 對象轉為 dict，添加 summary 和轉換後的時間
        rec_dict = {
            "id": rec.id,
            "user_id": rec.user_id,
            "camera_id": rec.camera_id,
            "s3_key": rec.s3_key,
            "duration": rec.duration,
            "is_processed": rec.is_processed,
            "is_embedding": rec.is_embedding,
            "size_bytes": rec.size_bytes,
            "upload_status": rec.upload_status.value if hasattr(rec.upload_status, 'value') else str(rec.upload_status),
            "start_time": start_time_user,
            "end_time": end_time_user,
            "video_metadata": rec.video_metadata,
            "summary": first_summary,  # 添加 summary
            "thumbnail_s3_key": rec.thumbnail_s3_key,  # 添加縮圖路徑
            "created_at": created_at_user,
            "updated_at": updated_at_user,
        }
        items_with_summary.append(rec_dict)
    
    return RecordingListResp(items=items_with_summary, total=total)


@recordings_router.patch("/{recording_id}/thumbnail")
async def update_recording_thumbnail(
    recording_id: uuid.UUID = Path(..., description="錄影 ID"),
    thumbnail_s3_key: str = Query(..., description="縮圖 S3 路徑"),
    db: AsyncSession = Depends(get_session),
    api_client = Depends(lambda: None)  # 內部 API，暫時不驗證
):
    """
    [內部] 更新錄影的縮圖路徑
    供 Compute Server 調用
    """
    stmt = select(recordings_table.Table).where(recordings_table.Table.id == recording_id)
    result = await db.execute(stmt)
    recording = result.scalar_one_or_none()
    
    if not recording:
        raise HTTPException(status_code=404, detail="錄影不存在")
    
    recording.thumbnail_s3_key = thumbnail_s3_key
    await db.commit()
    await db.refresh(recording)
    
    return {"ok": True, "recording_id": str(recording_id), "thumbnail_s3_key": thumbnail_s3_key}

@recordings_router.get("/{recording_id}/events", response_model=List[EventRead])
async def get_recording_events(
    request: Request,  # 🔧 修復：添加權限檢查
    recording_id: uuid.UUID = Path(..., description="錄影片段 ID"),
    sort: Optional[str] = Query(None, description="排序：`start_time|created_at|duration|id`，可 `:asc|:desc` 或 `-field`"),
    db: AsyncSession = Depends(get_session),
):
    """
    取得 **指定錄影底下的所有事件**（輕量，無複雜 join）。

    **Query 參數**
    - `sort`: 允許 `start_time|created_at|duration|id`；可 `:asc|:desc` 或 `-field`

    **呼叫範例**
    - 依事件開始時間新到舊：  
      `GET /recordings/{id}/events?sort=-start_time`
    """
    # 🔧 修復：添加權限檢查（先驗證 recording 是否存在且有權限訪問）
    current_user = request.state.current_user
    from ...DataAccess.tables.__Enumeration import Role
    
    stmt_rec = select(recordings_table.Table).where(recordings_table.Table.id == recording_id)
    rec = (await db.execute(stmt_rec)).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="recording not found")
    
    # 非管理員只能訪問自己的錄影事件
    if current_user.role != Role.admin and rec.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="沒有權限訪問此錄影的事件")
    
    allowed = {
        "start_time": events_table.Table.start_time,
        "created_at": getattr(events_table.Table, "created_at", events_table.Table.start_time),
        "duration": events_table.Table.duration,
        "id": events_table.Table.id,
    }
    order_by = _parse_sort(sort, allowed, default_key="start_time")

    stmt = (
        select(events_table.Table)
        .where(events_table.Table.recording_id == recording_id)
        .order_by(order_by)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return rows
