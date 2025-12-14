from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import date, datetime
import uuid

# ===== AI 選擇事件 =====
class VlogAISelectRequest(BaseModel):
    date: date
    summary_text: str | None = None # Optional override
    limit: int = Field(default=20, ge=10, le=100, description="建議的事件數量 (Top K)")

class VlogAISelectResponse(BaseModel):
    selected_event_ids: List[str]

# ===== 獲取日期的事件列表 =====
class EventInfo(BaseModel):
    """單個事件的簡要信息"""
    id: str
    action: str | None = None
    scene: str | None = None
    summary: str | None = None
    start_time: datetime | None = None
    duration: float | None = None
    recording_id: str | None = None
    
    model_config = ConfigDict(from_attributes=True)

class DateEventsResponse(BaseModel):
    """指定日期的事件列表"""
    date: date
    events: List[EventInfo]

# ===== 創建 Vlog =====
class VlogCreateRequest(BaseModel):
    """創建 Vlog 的請求"""
    target_date: date
    event_ids: List[str]  # 選中的事件 ID 列表
    title: str | None = None
    max_duration: int = Field(default=180, ge=30, le=180, description="最大時長(秒),最長3分鐘")
    resolution: str = Field(default="720p", pattern="^(480p|720p|1080p)$", description="輸出解析度")
    music_id: str | None = Field(default=None, description="選用的音樂 ID")
    music_start: float | None = Field(default=None, ge=0, description="音樂開始時間（秒）")
    music_end: float | None = Field(default=None, gt=0, description="音樂結束時間（秒）")
    music_fade: bool = Field(default=True, description="是否套用淡入淡出效果")
    music_volume: float | None = Field(default=None, ge=0.0, le=1.0, description="音樂音量（0~1，可選）")

class VlogCreateResponse(BaseModel):
    """創建 Vlog 的響應"""
    vlog_id: str
    status: str
    message: str

# ===== 獲取 Vlog 列表 =====
class VlogInfo(BaseModel):
    """Vlog 基本信息"""
    id: str
    title: str | None = None
    target_date: date
    status: str
    duration: float | None = None
    s3_key: str | None = None
    thumbnail_s3_key: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    progress: float | None = None
    status_message: str | None = None
    
    model_config = ConfigDict(from_attributes=True)

class VlogListResponse(BaseModel):
    """Vlog 列表響應"""
    items: List[VlogInfo]
    total: int

# ===== 獲取 Vlog 詳情 =====
class VlogSegmentInfo(BaseModel):
    """Vlog 片段信息"""
    recording_id: str
    event_id: str | None = None
    start_offset: float
    end_offset: float
    sequence_order: int
    
    model_config = ConfigDict(from_attributes=True)

class VlogDetailResponse(BaseModel):
    """Vlog 詳細信息"""
    id: str
    title: str | None = None
    target_date: date
    status: str
    duration: float | None = None
    s3_key: str | None = None
    thumbnail_s3_key: str | None = None
    settings: dict | None = None
    segments: List[VlogSegmentInfo]
    created_at: datetime
    updated_at: datetime | None = None
    progress: float | None = None
    status_message: str | None = None
    
    model_config = ConfigDict(from_attributes=True)

class DailyVlogResponse(BaseModel):
    """每日 Vlog 回應"""
    id: str
    title: str | None = None
    target_date: date
    status: str
    duration: float | None = None
    s3_key: str | None = None
    thumbnail_s3_key: str | None = None
    progress: float | None = None
    status_message: str | None = None
    error_message: str | None = None
    settings: dict | None = None
    created_at: datetime
    updated_at: datetime | None = None
    
    model_config = ConfigDict(from_attributes=True)

# ===== 獲取 Vlog 播放 URL =====
class VlogUrlResponse(BaseModel):
    """Vlog 播放 URL"""
    url: str
    ttl: int
    expires_at: int

# ===== 內部 API (供 Compute Server 使用) =====
class VlogInternalSegmentRequest(BaseModel):
    event_ids: List[str]

class VlogInternalSegmentInfoResponse(BaseModel):
    event_id: str
    recording_id: str
    s3_key: str
    start_offset: float
    duration: float
    recording_duration: float

class VlogStatusUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(processing|completed|failed)$")
    s3_key: str | None = None
    thumbnail_s3_key: str | None = None
    duration: float | None = None
    error_message: str | None = None
    progress: float | None = Field(default=None, ge=0.0, le=100.0)
    status_message: str | None = None
    job_id: str | None = None  # 用於同步更新 inference_jobs

class VlogStatusUpdateResponse(BaseModel):
    vlog_id: str
    status: str
    progress: float | None = None
    status_message: str | None = None
    s3_key: str | None = None
    thumbnail_s3_key: str | None = None
    duration: float | None = None

