# -*- coding: utf-8 -*-
from __future__ import annotations
import uuid
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

# ====== 共用回應 ======
class OkResp(BaseModel):
    ok: bool = True

# ====== 讀取 ======
class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    recording_id: Optional[uuid.UUID] = None
    action: Optional[str] = None
    scene: Optional[str] = None
    summary: Optional[str] = None
    objects: Optional[List[str]] = None
    start_time: Optional[datetime] = None
    duration: Optional[float] = None

    # 若你的 TimestampMixin 有這兩個欄位，保留；沒有也不影響
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class EventListResp(BaseModel):
    items: List[EventRead]
    item_total: int
    page_size: int
    page_now: int
    page_total: int

# ====== 更新 ======
class EventUpdate(BaseModel):
    recording_id: Optional[uuid.UUID] = None
    action: Optional[str] = Field(default=None, max_length=128)
    scene: Optional[str]  = Field(default=None, max_length=128)
    summary: Optional[str] = None
    objects: Optional[List[str]] = None
    start_time: Optional[datetime] = None
    duration: Optional[float] = None
