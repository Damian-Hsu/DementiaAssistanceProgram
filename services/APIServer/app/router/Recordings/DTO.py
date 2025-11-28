# -*- coding: utf-8 -*-
from __future__ import annotations
import uuid
from typing import Optional, List, Any
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

# ====== 共用回應 ======
class OkResp(BaseModel):
    ok: bool = True

# ====== 單筆錄影 ======
class RecordingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: int
    camera_id: Optional[uuid.UUID] = None
    s3_key: str
    duration: Optional[float] = None
    is_processed: bool
    is_embedding: bool
    size_bytes: Optional[int] = None
    upload_status: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    video_metadata: Optional[dict[str, Any]] = None
    summary: Optional[str] = None  # 🔧 修復：添加 summary 欄位（從關聯的 events 聚合）
    thumbnail_s3_key: Optional[str] = None  # 縮圖 S3 路徑

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class RecordingListResp(BaseModel):
    items: List[RecordingRead]
    total: int

class RecordingUrlResp(BaseModel):
    url: str
    ttl: int = Field(ge=30, le=7*24*3600)
    expires_at: int  # epoch seconds
    thumbnail_url: Optional[str] = None  # 縮圖 URL（如果有的話）

# ====== 事件（精簡版）======
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
    created_at: Optional[datetime] = None
