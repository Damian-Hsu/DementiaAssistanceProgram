# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field, AnyUrl
from typing import Optional, Literal
from datetime import datetime

class StartStreamReq(BaseModel):
    user_id: str
    camera_id: str
    rtsp_url: Optional[AnyUrl] = None 
    segment_seconds: Optional[int] = None
    align_first_cut: Optional[bool] = None
    startup_deadline_ts: Optional[int] = None

class UpdateStreamReq(BaseModel):
    user_id: str
    camera_id: str
    rtsp_url: Optional[AnyUrl] = None
    segment_seconds: Optional[int] = None
    align_first_cut: Optional[bool] = None
    startup_deadline_ts: Optional[int] = None
    # 這次更新是否要等舊的 stream 關閉（等舊的 ffmpeg 退場）
    graceful: bool = True

class StopStreamReq(BaseModel):
    user_id: str
    camera_id: str

class StreamInfo(BaseModel):
    stream_id: str = Field(..., description="userId-cameraId")
    user_id: str
    camera_id: str
    input_url: str
    record_dir: str
    segment_seconds: int
    align_first_cut: bool
    pid: Optional[int]
    status: Literal["starting", "running", "stopped", "error", "reconnecting"]
    cmdline: str
    error_message: Optional[str] = None
