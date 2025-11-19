# -*- coding: utf-8 -*-
from __future__ import annotations
import uuid
from typing import Optional, List, Tuple
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import InstrumentedAttribute

from ...DataAccess.Connect import get_session
from ...DataAccess.tables import events as events_table  # events_table.Table
from ...DataAccess.tables.__Enumeration import CameraStatus, Role
from ...router.User.service import UserService

from .DTO import (
    EventRead, EventListResp, EventUpdate, OkResp
)

# 與 camera 保持一致的風格；若你有 config 常數可替換
events_router = APIRouter(prefix="/events", tags=["events"])

# ====== User Service 實例 ======
user_service = UserService()

# ====== utils ======

async def _get_event_or_404(db: AsyncSession, id_: uuid.UUID) -> events_table.Table:
    stmt = select(events_table.Table).where(events_table.Table.id == id_)
    res = await db.execute(stmt)
    row = res.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="event not found")
    return row

def _local_date_to_utc_range(d: date, user_timezone: str = "Asia/Taipei") -> Tuple[datetime, datetime]:
    """
    把單一 'date' 轉成 UTC 的 [day_start, next_day_start) 範圍。
    使用使用者時區進行轉換。
    """
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

def _build_time_predicates(
    start_d: Optional[date],
    end_d: Optional[date],
    col: InstrumentedAttribute,
    user_timezone: str = "Asia/Taipei"
):
    """
    將 start_time / end_time 的 'date' 轉成對應的 datetime 範圍條件。
    使用使用者時區進行轉換。
    """
    preds = []
    if start_d and end_d:
        s0, _ = _local_date_to_utc_range(start_d, user_timezone)
        e0, _ = _local_date_to_utc_range(end_d, user_timezone)
        e0 = e0 + timedelta(days=0)  # end_d 本日 00:00 到 end_d+1 日 00:00
        preds.append(col >= s0)
        preds.append(col < e0 + timedelta(days=1))  # 包含 end_d 當日整天
    elif start_d and not end_d:
        s0, e0 = _local_date_to_utc_range(start_d, user_timezone)
        preds.append(col >= s0)
        preds.append(col < e0)
    elif end_d and not start_d:
        s0, e0 = _local_date_to_utc_range(end_d, user_timezone)
        preds.append(col >= s0)
        preds.append(col < e0)
    return preds

def _parse_sort(sort: Optional[str]) -> Tuple[InstrumentedAttribute, bool]:
    """
    回傳 (欄位, 是否降冪)
    支援：
      - "start_time", "created_at", "duration"
      - 前綴 '-' 代表 desc
      - "field:asc|desc"
    預設：start_time desc
    """
    default_col = getattr(events_table.Table, "start_time")
    default_desc = True

    if not sort:
        return default_col, default_desc

    raw = sort.strip().lower()

    desc = default_desc
    field = raw

    if ":" in raw:
        field, dir_ = raw.split(":", 1)
        dir_ = dir_.strip()
        if dir_ in ("asc", "desc"):
            desc = (dir_ == "desc")
    elif raw.startswith("-"):
        field = raw[1:]
        desc = True
    elif raw.startswith("+"):
        field = raw[1:]
        desc = False

    allowed = {
        "start_time": getattr(events_table.Table, "start_time"),
        "created_at": getattr(events_table.Table, "created_at", default_col),
        "duration": getattr(events_table.Table, "duration"),
        "id": getattr(events_table.Table, "id"),
    }
    col = allowed.get(field, default_col)
    return col, desc

def _apply_keyword_scope(
    keywords: Optional[str],
    sr: Optional[List[str]]
):
    """
    針對 keywords 與查詢範圍（sr）產生 OR 條件。
    sr 可包含：action / scene / summary / objects
    - 文字欄位用 ILIKE %kw%
    - objects (ARRAY) 用 contains([kw]) 做元素包含
    """
    if not keywords:
        return None

    kw = keywords.strip()
    if not kw:
        return None

    scope = set((sr or []) or [])
    valid = {"action", "scene", "summary", "objects"}
    if not scope:
        scope = valid
    else:
        scope = scope & valid
        if not scope:
            return None

    preds = []
    like = f"%{kw}%"

    if "action" in scope:
        preds.append(events_table.Table.action.ilike(like))
    if "scene" in scope:
        preds.append(events_table.Table.scene.ilike(like))
    if "summary" in scope:
        preds.append(events_table.Table.summary.ilike(like))
    if "objects" in scope:
        # 元素級的包含（完全相等的元素），若需子字串可改 ANY(unnest(...)) ILIKE
        preds.append(events_table.Table.objects.contains([kw]))

    if not preds:
        return None
    return or_(*preds)

# ====== 路由 ======

@events_router.get("/", response_model=EventListResp)
async def list_events(
    request: Request,
    recording_id: Optional[uuid.UUID] = Query(default=None),
    user_id: Optional[int] = Query(default=None, description="指定使用者 ID（僅管理員可用）"),
    start_time: Optional[date] = Query(default=None, description="ISO local date"),
    end_time: Optional[date] = Query(default=None, description="ISO local date"),
    keywords: Optional[str] = Query(default=None, description="查詢 action / scene / summary / objects"),
    sr: Optional[List[str]] = Query(default=None, description="查詢範圍，多值：?sr=action&sr=scene&sr=objects"),
    sort: Optional[str] = Query(default=None, description="欄位：start_time|created_at|duration；加 :asc|:desc 或前綴 +/-"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
    
):
    """
    事件列表（可篩選 recording / 時間區間 / 關鍵字 / 排序 + 分頁）
    """
    current_user = request.state.current_user
    
    # 獲取使用者時區
    user_timezone = user_service.get_user_timezone(current_user)
    
    conds = []
    
    # 權限控制：使用者 ID 過濾
    if current_user.role == Role.admin:
        # 管理員：可以使用手動輸入的 user_id，如果沒有則使用自己的 ID
        target_user_id = user_id if user_id is not None else current_user.id
        conds.append(events_table.Table.user_id == target_user_id)
    else:
        # 一般使用者：只能查詢自己的事件，忽略手動輸入的 user_id
        conds.append(events_table.Table.user_id == current_user.id)
    
    if recording_id:
        conds.append(events_table.Table.recording_id == recording_id)

    # 時間條件（使用使用者時區）
    conds += _build_time_predicates(start_time, end_time, events_table.Table.start_time, user_timezone)

    # 關鍵字 + 範圍
    kw_pred = _apply_keyword_scope(keywords, sr)
    if kw_pred is not None:
        conds.append(kw_pred)

    # 排序
    order_col, is_desc = _parse_sort(sort)
    order_by = order_col.desc() if is_desc else order_col.asc()

    # 查 items
    stmt_items = (
        select(events_table.Table)
        .where(and_(*conds)) if conds else select(events_table.Table)
    )
    stmt_items = stmt_items.order_by(order_by).offset((page - 1) * size).limit(size)

    # 查 total
    base_sel = select(events_table.Table)
    if conds:
        base_sel = base_sel.where(and_(*conds))
    stmt_total = select(func.count()).select_from(base_sel.subquery())

    rows = (await db.execute(stmt_items)).scalars().all()
    total = (await db.execute(stmt_total)).scalar_one()

    # 轉換時間到使用者時區
    import pytz
    user_tz = pytz.timezone(user_timezone)
    for row in rows:
        if row.start_time:
            if row.start_time.tzinfo is None:
                row.start_time = row.start_time.replace(tzinfo=timezone.utc)
            row.start_time = row.start_time.astimezone(user_tz)
        if hasattr(row, 'created_at') and row.created_at:
            if row.created_at.tzinfo is None:
                row.created_at = row.created_at.replace(tzinfo=timezone.utc)
            row.created_at = row.created_at.astimezone(user_tz)
        if hasattr(row, 'updated_at') and row.updated_at:
            if row.updated_at.tzinfo is None:
                row.updated_at = row.updated_at.replace(tzinfo=timezone.utc)
            row.updated_at = row.updated_at.astimezone(user_tz)

    return EventListResp(
        items=rows,
        item_total=total,
        page_size=size,
        page_now=page,
        page_total=total // size + (1 if total % size > 0 else 0),
    )


@events_router.get("/{event_id}", response_model=EventRead)
async def get_event(
    request: Request,
    event_id: uuid.UUID = Path(...),
    db: AsyncSession = Depends(get_session),
):
    """
    取得單一事件內容
    """
    current_user = request.state.current_user
    user_timezone = user_service.get_user_timezone(current_user)
    
    ev = await _get_event_or_404(db, event_id)
    
    # 轉換時間到使用者時區
    import pytz
    user_tz = pytz.timezone(user_timezone)
    if ev.start_time:
        if ev.start_time.tzinfo is None:
            ev.start_time = ev.start_time.replace(tzinfo=timezone.utc)
        ev.start_time = ev.start_time.astimezone(user_tz)
    if hasattr(ev, 'created_at') and ev.created_at:
        if ev.created_at.tzinfo is None:
            ev.created_at = ev.created_at.replace(tzinfo=timezone.utc)
        ev.created_at = ev.created_at.astimezone(user_tz)
    if hasattr(ev, 'updated_at') and ev.updated_at:
        if ev.updated_at.tzinfo is None:
            ev.updated_at = ev.updated_at.replace(tzinfo=timezone.utc)
        ev.updated_at = ev.updated_at.astimezone(user_tz)
    
    return ev


@events_router.patch("/{event_id}", response_model=OkResp)
async def update_event(
    event_id: uuid.UUID,
    req: EventUpdate,
    db: AsyncSession = Depends(get_session),
):
    """
    更新事件（部分欄位）
    """
    ev = await _get_event_or_404(db, event_id)
    patch = req.model_dump(exclude_unset=True)
    for k, v in patch.items():
        setattr(ev, k, v)
    db.add(ev)
    await db.commit()
    return OkResp()

@events_router.delete("/{event_id}", response_model=OkResp)
async def delete_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """
    刪除事件
    """
    ev = await _get_event_or_404(db, event_id)
    try:
        await db.delete(ev)
        await db.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail="delete event failed") from e
    return OkResp()