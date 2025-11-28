# -*- coding: utf-8 -*-
from __future__ import annotations
import uuid
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, date
from pydantic import BaseModel, ConfigDict, Field

# ====== 共用回應 ======
class OkResp(BaseModel):
    ok: bool = True

# ====== 事件讀取（精簡版）======
class EventSimple(BaseModel):
    """查詢結果中的事件（精簡版）"""
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    recording_id: Optional[uuid.UUID] = None
    action: Optional[str] = None
    scene: Optional[str] = None
    summary: Optional[str] = None
    objects: Optional[List[str]] = None
    start_time: Optional[datetime] = None
    duration: Optional[float] = None

# ====== 影片讀取（精簡版）======
class RecordingSimple(BaseModel):
    """查詢結果中的影片（精簡版）"""
    id: str
    time: str
    duration: float
    summary: Optional[str] = None
    action: Optional[str] = None
    scene: Optional[str] = None
    thumbnail_s3_key: Optional[str] = None

# ====== 日記讀取（精簡版）======
class DiarySimple(BaseModel):
    """查詢結果中的日記（精簡版）"""
    date: str
    content: Optional[str] = None
    exists: bool = False
    success: Optional[bool] = None
    message: Optional[str] = None

# ====== Vlog讀取（精簡版）======
class VlogSimple(BaseModel):
    """查詢結果中的Vlog（精簡版）"""
    id: str
    title: Optional[str] = None
    date: str
    status: str
    duration: Optional[float] = None
    thumbnail_s3_key: Optional[str] = None

# ====== 對話訊息 ======
class ChatMessage(BaseModel):
    """單條對話訊息"""
    role: Literal["user", "assistant", "system"] = Field(..., description="訊息角色")
    content: str = Field(..., description="訊息內容")
    timestamp: Optional[datetime] = Field(None, description="訊息時間戳")

# ====== 函數調用結果 ======
class FunctionCallResult(BaseModel):
    """函數調用結果"""
    function_name: str = Field(..., description="函數名稱")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="函數參數")
    result: Any = Field(None, description="函數返回結果")

# ====== 聊天請求（支持對話歷史）======
class ChatRequest(BaseModel):
    """對話式聊天請求"""
    message: str = Field(..., description="用戶訊息", min_length=1, max_length=500)
    history: List[ChatMessage] = Field(default_factory=list, description="對話歷史（最多保留最近 10 條）")
    date_from: Optional[date] = Field(None, description="查詢起始日期（ISO format）")
    date_to: Optional[date] = Field(None, description="查詢結束日期（ISO format）")
    max_results: int = Field(10, ge=1, le=50, description="每次函數調用最多返回結果數")

# ====== 聊天回應 ======
class ChatResponse(BaseModel):
    """對話式聊天回應"""
    message: str = Field(..., description="AI 回覆訊息")
    events: List[EventSimple] = Field(default_factory=list, description="相關事件列表")
    recordings: List[RecordingSimple] = Field(default_factory=list, description="相關影片列表")
    diaries: List[DiarySimple] = Field(default_factory=list, description="相關日記列表")
    vlogs: List[VlogSimple] = Field(default_factory=list, description="相關Vlog列表")
    function_calls: List[FunctionCallResult] = Field(default_factory=list, description="本次調用的函數列表")
    has_more: bool = Field(False, description="是否還有更多結果可查詢")
    total_events: int = Field(0, description="符合條件的事件總數")
    total_recordings: int = Field(0, description="符合條件的影片總數")
    total_diaries: int = Field(0, description="符合條件的日記總數")
    total_vlogs: int = Field(0, description="符合條件的Vlog總數")

# ====== 日記相關 DTO ======
class DiarySummaryRequest(BaseModel):
    """日記摘要請求"""
    diary_date: date = Field(..., description="日記日期（ISO format）")
    force_refresh: bool = Field(default=False, description="是否強制刷新（忽略哈希檢查）")

class DiarySummaryResponse(BaseModel):
    """日記摘要回應"""
    diary_date: date = Field(..., description="日記日期")
    content: str | None = Field(None, description="日記內容")
    events_count: int = Field(0, description="事件數量")
    is_refreshed: bool = Field(False, description="是否已刷新")