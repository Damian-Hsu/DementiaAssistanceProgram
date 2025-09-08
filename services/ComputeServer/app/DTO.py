from enum import Enum
from pydantic import BaseModel, Field, model_validator
from typing import Dict, Optional, Any, List
from datetime import datetime
from uuid import UUID

class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"

class JobType(str, Enum):
    VIDEO_DESCRIPTION = "video_description_extraction" #影像轉描述任務
    ECHO_AND_CHECK = "echo_and_check" #測試任務

class JobBase(BaseModel):
    job_id: str
    trace_id: Optional[str] = None


class JobCreate(JobBase):
    type: JobType
    input_url: str  # 片段檔案或遠端 URL
    video_start_time: Optional[datetime] = None  # 影片起始時間
    params: Dict[str, Any] = Field(default_factory=dict)
    """
    params defines
    {
    video_id: str, # 影片ID(如果有的話)

    target_fps: int, # 抽幀後的幀率，預設為3秒一幀。
    blur_threshold: float, # 模糊閾值，預設為20.0
    difference_module: "SSIM",
    difference_threshold: 0.7,
    compression_proportion: 0.5
    }
    """

class EventItem(BaseModel):
    """
    場景格式設計:
    "events":[{
        "start_time": "0.0", 
        "end_time": "10.0", # 事件的開始和結束時間（秒）
        "summary": "...", #放入事件摘要
        "objects": ["碗","手",...], #放入物件名稱列表
        "scene": "餐廳", # 放入場景描述
        "action": "吃飯" # scene and action具有唯一性
        },
        ...
    ]
    """
    start_time: float
    end_time: float
    summary: str
    objects: List[str] = Field(default_factory=list)
    scene: Optional[str] = None
    action: Optional[str] = None

    
class JobResult(JobBase):
    """
    任務處理完後返回的格式
    """
    status: JobStatus #任務狀態
    recording_id: Optional[UUID] = None  # 對應的錄影ID
    video_start_time : Optional[datetime] = None  # 影片起始時間,iso格式
    video_end_time: Optional[datetime] = None  # 影片結束時間,iso格式
    error_code: Optional[str] = None  # e.g. DECODE_FAIL / LLM_TIMEOUT
    error_message: Optional[str] = None
    duration: Optional[float] = None #影片時長
    metrics: Optional[Dict] = None #模型表現指標
    events: List[EventItem] = Field(default_factory=list)  # 事件列表
    # 規則：FAILED 必須有 error_code / error_message；SUCCESS不該帶錯誤
    @model_validator(mode="after")
    def _validate_error_fields(self):
        #如果後面正式上線，這些raise最好使用英文(寫在這邊提醒以後的我)2025/8/15
        if self.status == JobStatus.FAILED:
            if not self.error_code or not self.error_message:
                raise ValueError("FAILED 必須附上 error_code 與 error_message")
        if self.status == JobStatus.SUCCESS:
            if self.error_code or self.error_message:
                raise ValueError("SUCCESS 不應包含 error_code/error_message")
        return self