from __future__ import annotations
from pydantic import BaseModel
from uuid import UUID


class ApiKeyCreateDTO(BaseModel):
    name: str
    owner_id: int   
    rate_limit_per_min: int | None = None
    quota_per_day: int | None = None
    scopes: list[str] | None = None  # 可選作用域


class ApiKeyOutDTO(BaseModel):
    id: UUID
    name: str
    owner_id: int
    active: bool
    rate_limit_per_min: int | None = None
    quota_per_day: int | None = None
    scopes: list[str] | None = None

    class Config:
        from_attributes = True  # 允許 SQLAlchemy ORM 自動轉換


class ApiKeySecretOutDTO(ApiKeyOutDTO):
    token: str  # 建立或 rotate 時才回傳一次


class ApiKeyPatchDTO(BaseModel):
    name: str | None = None
    active: bool | None = None
    rate_limit_per_min: int | None = None
    quota_per_day: int | None = None
    scopes: list[str] | None = None


# ====== 系統設定相關 DTO ======

class SetDefaultGoogleApiKeyDTO(BaseModel):
    """設置預設 Google API Key"""
    api_key: str
    description: str | None = None


class DefaultGoogleApiKeyResponse(BaseModel):
    """預設 Google API Key 回應"""
    api_key: str | None = None
    description: str | None = None
    updated_at: str | None = None


class SetDefaultLLMDTO(BaseModel):
    """設置系統預設 LLM 供應商與模型（全系統共享，僅管理員可修改）"""

    default_llm_provider: str
    default_llm_model: str
    description: str | None = None


class DefaultLLMResponse(BaseModel):
    """系統預設 LLM 回應"""

    default_llm_provider: str
    default_llm_model: str
    description: str | None = None
    updated_at: str | None = None


class SetVideoParamsDTO(BaseModel):
    """設置影片參數（系統層級，僅管理員可修改）"""
    segment_seconds: int  # 秒
    description: str | None = None


class VideoParamsResponse(BaseModel):
    """影片參數回應"""
    segment_seconds: int
    description: str | None = None
    updated_at: str | None = None


class SetDefaultAiKeyLimitsDTO(BaseModel):
    """設置系統預設 AI API Key（預設 key）使用量限制（每位使用者）"""
    rpm: int  # requests per minute
    rpd: int  # requests per day
    description: str | None = None


class DefaultAiKeyLimitsResponse(BaseModel):
    """系統預設 AI API Key（預設 key）限制回應"""
    rpm: int
    rpd: int
    description: str | None = None
    updated_at: str | None = None


# ====== 黑名單相關 DTO ======

class AddToBlacklistDTO(BaseModel):
    """添加到黑名單"""
    user_id: int
    reason: str | None = None


class BlacklistEntryDTO(BaseModel):
    """黑名單條目"""
    user_id: int
    user_account: str
    user_name: str
    reason: str | None = None
    created_at: str

    class Config:
        from_attributes = True


# ====== 使用者統計相關 DTO ======

class UserStatsDTO(BaseModel):
    """使用者統計"""
    user_id: int
    account: str
    name: str
    total_token_usage: int = 0  # 總 Token 使用量（需要從日記或其他地方計算）
    total_chat_messages: int = 0  # 總聊天訊息數量（需要從日記或其他地方計算）
    is_blacklisted: bool = False  # 是否在黑名單中
    use_default_api_key: bool = True  # 是否使用預設 API Key


# ====== 使用者詳情（Admin） ======

class UserDetailDTO(BaseModel):
    """使用者詳情（僅管理員可看；包含 password_hash）"""
    user_id: int
    account: str
    name: str
    role: str
    gender: str
    birthday: str | None = None
    phone: str
    email: str
    headshot_url: str | None = None
    password_hash: str
    active: bool
    settings: dict | None = None
    is_blacklisted: bool = False
    blacklist_reason: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class UpdateUserActiveDTO(BaseModel):
    """管理員更新使用者啟用狀態"""
    active: bool


# ====== 任務相關 DTO ======

class TaskInfoDTO(BaseModel):
    """任務資訊"""
    task_id: str  # job_id 或 stream_id
    task_type: str  # "video_description", "vlog_generation", "diary_generation", "streaming"
    status: str  # "pending", "processing", "running", "success", "failed", "error", "stopped", "reconnecting"
    user_id: int | None = None
    camera_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    progress: float | None = None  # 0.0 - 100.0
    error_message: str | None = None
    details: dict | None = None  # 任務詳細資訊


class TaskListRespDTO(BaseModel):
    """任務列表回應"""
    items: list[TaskInfoDTO]
    item_total: int
    page_size: int
    page_now: int
    page_total: int