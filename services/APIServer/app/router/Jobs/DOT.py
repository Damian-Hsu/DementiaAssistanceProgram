from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime 

class JobParams(BaseModel):
    video_id: str | None = None  # 影片ID(如果有的話)
    video_start_time: datetime | None = None
    target_fps: int | None = None  # 抽幀後的幀率，預設為3秒一幀。
    blur_threshold: float | None = None # 模糊閾值，預設為20.0
    difference_module: str | None = None
    difference_threshold: float | None = None
    compression_proportion: float | None = None

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

