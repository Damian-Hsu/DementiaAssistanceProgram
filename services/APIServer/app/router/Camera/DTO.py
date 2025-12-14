# -*- coding: utf-8 -*-
from __future__ import annotations
import uuid
from typing import Optional, List, Literal, Any
from datetime import datetime
import ipaddress
from pydantic import BaseModel, Field, ConfigDict, field_validator
from ...DataAccess.tables.__Enumeration import CameraStatus
# ====== 共用回應 ======
class OkResp(BaseModel):
    ok: bool = True

class TokenVersionResp(BaseModel):
    token_version: int

# ====== 建立 / 更新 ======
class CameraCreate(BaseModel):
    # user_id：一般使用者不允許指定（會強制使用自己的 id）；管理員才可指定
    user_id: Optional[int] = None
    name: str = Field(max_length=128)
    # allow_ip: Optional[List[str]] = None
    max_publishers: Optional[int] = Field(default=1, ge=1)

    # @field_validator("allow_ip")
    # @classmethod
    # def _normalize_cidr(cls, v):
    #     """
    #     僅做基本格式檢查（可為 IPv4/IPv6 或 CIDR），實際比對交由 DB / 驗證端。
    #     """
    #     if v is None:
    #         return v
        
    #     norm: list[str] = []
    #     for item in v:
    #         try:
    #             net = ipaddress.ip_network(item, strict=False)  # 支援單一 IP，自動轉 /32
    #             norm.append(str(net))
    #         except ValueError as _:
    #             raise ValueError(f"invalid ip/cidr: {item}")
    #     return norm

class CameraUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    # allow_ip: Optional[List[str]] = None
    max_publishers: Optional[int] = Field(default=None, ge=1)
    status: Optional[CameraStatus] = None

    # @field_validator("allow_ip")
    # @classmethod
    # def _normalize_cidr(cls, v):
    #     if v is None:
    #         return v
    #     import ipaddress
    #     norm: list[str] = []
    #     for item in v:
    #         try:
    #             net = ipaddress.ip_network(item, strict=False)
    #             norm.append(str(net))
    #         except ValueError:
    #             raise ValueError(f"invalid ip/cidr: {item}")
    #     return norm

# ====== 狀態 ======
class CameraStatusReq(BaseModel):
    status: Literal["inactive", "active", "deleted"]

# ====== 讀取 ======
class CameraRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: int
    name: str
    status: str
    token_version: int
    # allow_ip: Optional[List[str]] = None
    last_seen_at: Optional[datetime] = None
    max_publishers: int

class CameraListResp(BaseModel):
    items: list[CameraRead]
    total: int

# ====== 產 Token ======
class GenerateTokenReq(BaseModel):
    action: Literal["publish", "read"] = "publish"
    # ⚠️ 重要：這裡不能預設 30，否則即使前端不傳值，也會被 Pydantic 補成 30，
    # 造成 connect_stream 永遠不會去讀取「管理員設定」的 video_segment_seconds。
    segment_seconds: Optional[int] = Field(default=None, ge=1, le=600, description="影片切片長度（秒）；未提供則使用系統設定，最後 fallback 30")  # 秒
    ttl: Optional[int] = Field(default=None, ge=300, le=21600)  # 秒（RTSP 推流：300-21600）
    # bind_ip: bool = True  # 是否把 request 來源 IP 綁進 token

class StreamConnectResp(BaseModel):
    ttl: int
    info: Optional[dict[str, Any]] = None  # streaming 回傳的 JSON（僅成功時）

class RefreshTokenResp(BaseModel):
    audience: Literal["rtsp", "webrtc"]
    action: Literal["publish", "read"]
    token: str
    ttl: int
    expires_at: int
class PublishRTSPURLResp(BaseModel):
    publish_rtsp_url: str
    ttl: int
    expires_at: int
class PlayWebRTCURLResp(BaseModel):
    play_webrtc_url: str
    ttl: int
    expires_at: int

class StreamStatusResp(BaseModel):
    is_streaming: bool
    status: Optional[Literal["starting", "running", "stopped", "error", "reconnecting"]] = None
    stream_info: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None