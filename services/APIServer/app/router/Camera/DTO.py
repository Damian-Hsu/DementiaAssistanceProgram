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
    user_id: int
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
    segment_seconds: int = Field(default=30, ge=1, le=600)  # 秒
    ttl: Optional[int] = Field(default=None, ge=30, le=3600)  # 秒
    # bind_ip: bool = True  # 是否把 request 來源 IP 綁進 token

class StreamConnectResp(BaseModel):
    ttl: int
    info: Optional[dict[str, Any]] = None  # streaming 回傳的 JSON（僅成功時）

class RefreshTokenResp(BaseModel):
    audience: Literal["rtsp", "hls", "webrtc"]
    action: Literal["publish", "read"]
    token: str
    ttl: int
    expires_at: int
class PublishRTSPURLResp(BaseModel):
    publish_rtsp_url: str
    ttl: int
    expires_at: int
class PlayHLSURLResp(BaseModel):
    play_hls_url: str
    ttl: int
    expires_at: int
class PlayWebRTCURLResp(BaseModel):
    play_webrtc_url: str
    ttl: int
    expires_at: int