# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import uuid
from typing import Optional, List, Tuple
from datetime import date, datetime, time, timedelta, timezone

import boto3
from botocore.config import Config

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, delete, exists

from ...DataAccess.Connect import get_session
from ...DataAccess.tables import recordings as recordings_table  # recordings_table.Table
from ...DataAccess.tables import events as events_table          # events_table.Table

from .DTO import (
    RecordingRead, RecordingListResp, RecordingUrlResp, OkResp, EventRead
)

# ------------------------------------------------------------
# Router
# ------------------------------------------------------------
recordings_router = APIRouter(prefix="/recordings", tags=["recordings"])

# ------------------------------------------------------------
# S3/MinIO：你可把下列兩函式改成你「已驗證成功」的封裝
# ------------------------------------------------------------
# 對外可達的 endpoint（可改成主機 IP 或網域）：例如 http://localhost:9000
PUBLIC_MINIO_ENDPOINT = os.getenv("PUBLIC_MINIO_ENDPOINT", "http://localhost:9000")

S3_ENDPOINT   = PUBLIC_MINIO_ENDPOINT          # ← 關鍵：外部可連到
S3_ACCESS_KEY = os.getenv("MINIO_ROOT_USER",  os.getenv("S3_ACCESS_KEY", "minioadmin"))
S3_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", os.getenv("S3_SECRET_KEY", "minioadmin"))
S3_REGION     = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET     = os.getenv("MINIO_BUCKET", "media-bucket")

# 一律用 path-style，避免變成 videos.minio:9000 這種外部解析不到的子網域
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

    return key

def _presign_get(key: str, ttl: int, *, disposition: Optional[str], filename: Optional[str]) -> str:
    key = _normalize_key(key)  # 如果你有這支，保留
    params = {"Bucket": S3_BUCKET, "Key": key}

    # 讓瀏覽器以串流播放
    params["ResponseContentType"] = "video/mp4"

    # 預設 inline；若你從 query 傳進來就尊重使用者
    disp = disposition or "inline"
    safe_name = filename or key.rsplit("/", 1)[-1]
    params["ResponseContentDisposition"] = f'{disp}; filename="{safe_name}"'

    return _s3.generate_presigned_url("get_object", Params=params, ExpiresIn=int(ttl))

def _delete_object(key: str) -> None:
    """刪除物件；不存在也視為成功（S3 的語意即是冪等）。"""
    _s3.delete_object(Bucket=S3_BUCKET, Key=key)

# ------------------------------------------------------------
# Utils
# ------------------------------------------------------------
def _date_to_utc_range(d: date) -> Tuple[datetime, datetime]:
    """把 local ISO date 轉為該日 UTC [00:00, 次日00:00)。"""
    start = datetime.combine(d, time.min).replace(tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end

def _build_time_preds(start_d: Optional[date], end_d: Optional[date], col):
    preds = []
    if start_d and end_d:
        s0, _ = _date_to_utc_range(start_d)
        e0, _ = _date_to_utc_range(end_d)
        preds.extend([col >= s0, col < (e0 + timedelta(days=1))])
    elif start_d:
        s0, e0 = _date_to_utc_range(start_d)
        preds.extend([col >= s0, col < e0])
    elif end_d:
        s0, e0 = _date_to_utc_range(end_d)
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
    """
    stmt = select(recordings_table.Table).where(recordings_table.Table.id == recording_id)
    rec = (await db.execute(stmt)).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="recording not found")

    url = _presign_get(rec.s3_key, ttl, disposition=disposition, filename=filename)
    now = int(datetime.now(timezone.utc).timestamp())
    return RecordingUrlResp(url=url, ttl=ttl, expires_at=now + ttl)


@recordings_router.delete("/{recording_id}", response_model=OkResp, status_code=status.HTTP_200_OK)
async def delete_recording(
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
    stmt = select(recordings_table.Table).where(recordings_table.Table.id == recording_id)
    rec = (await db.execute(stmt)).scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="recording not found")

    try:
        _delete_object(rec.s3_key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"s3 delete failed: {e}")

    # 若你的 DB 已設 CASCADE，可移除以下兩段 delete
    await db.execute(delete(events_table.Table).where(events_table.Table.recording_id == recording_id))
    await db.execute(delete(recordings_table.Table).where(recordings_table.Table.id == recording_id))
    await db.commit()
    return OkResp()


@recordings_router.get("/", response_model=RecordingListResp)
async def list_recordings(
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
    conds = []
    conds += _build_time_preds(start_time, end_time, recordings_table.Table.start_time)

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
    return RecordingListResp(items=rows, total=total)


@recordings_router.get("/{recording_id}/events", response_model=List[EventRead])
async def get_recording_events(
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
