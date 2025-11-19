from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime 

# 目前數值從這裡生效
class JobParams(BaseModel):
    video_id: UUID | None = None  # 影片ID(如果有的話)
    user_id: int | None = None  # 使用者ID(如果有的話)
    camera_id: UUID | None = None  # 攝影機ID(如果有的話)
    video_start_time: datetime | None = None
    target_fps: int = 3  # 抽幀後的幀率，預設為3秒一幀。
    blur_threshold: float  = 60 # 模糊閾值，預設為20.0
    difference_module: str = "SSIM"
    difference_threshold: float  = 0.7
    compression_proportion: float  = 0.5

class JobCreateDTO(BaseModel):
    type: str = Field(..., description="例如 video_description_extraction")
    input_type: str = Field(description="例如 video")
    input_url: str
    trace_id: str | None = None
    params: JobParams
    """
    params defines
    {
    video_id: str, # 影片ID(如果有的話)
    video_start_time: str | None = None  # ISO 格式
    target_fps: 2, # 抽幀後的幀率，預設為3秒一幀。
    blur_threshold: 60, # 模糊閾值，預設為20.0
    difference_module: "SSIM",
    difference_threshold: 0.7,
    compression_proportion: 0.5
    }
    """

class JobCreatedRespDTO(BaseModel):
    job_id: UUID
    trace_id: str | None = None
    status: str = "pending"

class JobGetRespDTO(BaseModel):
    job_id: UUID
    type: str
    status: str
    input_type: str
    input_url: str
    output_url: str | None
    trace_id: str | None
    duration: float | None
    error_code: str | None
    error_message: str | None
    params: dict | None
    metrics: dict | None

class JobStatusRespDTO(BaseModel):
    status: str

class JobCompleteDTO(BaseModel):
    job_id: UUID
    trace_id: str | None = None
    status: str
    video_start_time: str | None = None  # ISO 格式
    video_end_time: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    duration: float | None = None
    metrics: dict | None = None
    events: list | None = None
class JobListRespDTO(BaseModel):
    items: list[JobGetRespDTO]
    total: int
    page: int
    size: int
    page_total: int

class OKRespDTO(BaseModel):
    msg: str = "OK"


