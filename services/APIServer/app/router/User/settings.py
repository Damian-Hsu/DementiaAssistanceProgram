# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator
import pytz


# ====== LLM API 設定 ======

class LLMProviderConfig(BaseModel):
    """單一 LLM 供應商設定"""
    api_key: str = Field(..., description="API 金鑰")
    model_names: List[str] = Field(default_factory=list, description="可用的模型名稱列表")
    
    @field_validator('api_key')
    def validate_api_key(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError("API 金鑰不能為空")
        return v.strip()
    
    @field_validator('model_names')
    def validate_model_names(cls, v):
        # 允許 model_names 為空，因為可以稍後再設定
        if not v:
            return []
        return [name.strip() for name in v if name.strip()]


class LLMModelAPIConfig(BaseModel):
    """LLM 模型 API 設定"""
    providers: Dict[str, LLMProviderConfig] = Field(default_factory=dict, description="供應商設定")
    
    def get_provider_config(self, provider_name: str) -> Optional[LLMProviderConfig]:
        """獲取指定供應商的設定"""
        return self.providers.get(provider_name)
    
    def add_provider(self, provider_name: str, config: LLMProviderConfig):
        """添加供應商設定"""
        self.providers[provider_name] = config
    
    def remove_provider(self, provider_name: str):
        """移除供應商設定"""
        if provider_name in self.providers:
            del self.providers[provider_name]


# ====== 使用者設定 ======

class UserSettings(BaseModel):
    """使用者設定模型"""
    
    # 時區設定
    timezone: str = Field(default="Asia/Taipei", description="使用者時區")
    
    # LLM 設定
    llm_model_api: LLMModelAPIConfig = Field(default_factory=LLMModelAPIConfig, description="LLM 模型 API 設定")
    
    # 預設 LLM 供應商和模型
    default_llm_provider: str = Field(default="google", description="預設 LLM 供應商")
    default_llm_model: str = Field(default="gemini-2.0-flash", description="預設 LLM 模型（使用穩定版本，免費層支持）")
    
    # 其他設定
    language: str = Field(default="zh-TW", description="語言設定")
    theme: str = Field(default="light", description="主題設定")
    notifications_enabled: bool = Field(default=True, description="是否啟用通知")
    
    # 日記自動刷新設定
    diary_auto_refresh_enabled: bool = Field(default=True, description="是否啟用日記自動刷新")
    diary_auto_refresh_interval_minutes: int = Field(default=30, ge=5, le=1440, description="日記自動刷新間隔（分鐘）")
    
    # 串流 TTL 設定
    default_stream_ttl: int = Field(default=300, ge=30, le=3600, description="預設串流 TTL（秒），範圍：30-3600")
    
    @field_validator('timezone')
    def validate_timezone(cls, v):
        """驗證時區是否有效"""
        try:
            pytz.timezone(v)
            return v
        except pytz.exceptions.UnknownTimeZoneError:
            raise ValueError(f"無效的時區: {v}")
    
    @field_validator('default_llm_provider')
    def validate_default_provider(cls, v):
        """驗證預設供應商"""
        if not v or len(v.strip()) == 0:
            raise ValueError("預設供應商不能為空")
        return v.strip()
    
    @field_validator('default_llm_model')
    def validate_default_model(cls, v):
        """驗證預設模型"""
        if not v or len(v.strip()) == 0:
            raise ValueError("預設模型不能為空")
        return v.strip()
    
    def get_timezone_info(self) -> pytz.BaseTzInfo:
        """獲取時區資訊"""
        return pytz.timezone(self.timezone)
    
    def convert_utc_to_user_timezone(self, utc_datetime: datetime) -> datetime:
        """將 UTC 時間轉換為使用者時區"""
        if utc_datetime.tzinfo is None:
            utc_datetime = utc_datetime.replace(tzinfo=timezone.utc)
        user_tz = self.get_timezone_info()
        return utc_datetime.astimezone(user_tz)
    
    def convert_user_timezone_to_utc(self, user_datetime: datetime) -> datetime:
        """將使用者時區時間轉換為 UTC"""
        if user_datetime.tzinfo is None:
            user_tz = self.get_timezone_info()
            user_datetime = user_tz.localize(user_datetime)
        return user_datetime.astimezone(timezone.utc)
    
    def get_llm_config(self) -> tuple[str, str, Optional[str]]:
        """獲取 LLM 設定 (provider, model, api_key)"""
        provider_config = self.llm_model_api.get_provider_config(self.default_llm_provider)
        api_key = provider_config.api_key if provider_config else None
        
        # 如果沒有設定 API Key，使用預設的
        if not api_key:
            api_key = None  # 將使用系統預設的 API Key
        
        return self.default_llm_provider, self.default_llm_model, api_key


# ====== 預設設定 ======

def get_default_user_settings() -> UserSettings:
    """獲取預設使用者設定"""
    return UserSettings(
        timezone="Asia/Taipei",
        llm_model_api=LLMModelAPIConfig(),
        default_llm_provider="google",
        default_llm_model="gemini-2.0-flash",
        language="zh-TW",
        theme="light",
        notifications_enabled=True,
        diary_auto_refresh_enabled=True,
        diary_auto_refresh_interval_minutes=30,
        default_stream_ttl=300
    )


def create_user_settings_with_llm_config(
    provider: str,
    api_key: str,
    model_names: List[str],
    timezone: str = "Asia/Taipei"
) -> UserSettings:
    """創建包含 LLM 設定的使用者設定"""
    llm_config = LLMModelAPIConfig()
    llm_config.add_provider(provider, LLMProviderConfig(
        api_key=api_key,
        model_names=model_names
    ))
    
    return UserSettings(
        timezone=timezone,
        llm_model_api=llm_config,
        default_llm_provider=provider,
        default_llm_model=model_names[0] if model_names else "gemini-2.0-flash",
        language="zh-TW",
        theme="light",
        notifications_enabled=True,
        diary_auto_refresh_enabled=True,
        diary_auto_refresh_interval_minutes=30,
        default_stream_ttl=300
    )


# ====== 設定更新 DTO ======

class UpdateUserSettingsRequest(BaseModel):
    """更新使用者設定請求"""
    timezone: Optional[str] = Field(None, description="時區設定")
    language: Optional[str] = Field(None, description="語言設定")
    theme: Optional[str] = Field(None, description="主題設定")
    notifications_enabled: Optional[bool] = Field(None, description="是否啟用通知")
    
    # LLM 設定
    default_llm_provider: Optional[str] = Field(None, description="預設 LLM 供應商")
    default_llm_model: Optional[str] = Field(None, description="預設 LLM 模型")
    
    # LLM API 設定
    llm_providers: Optional[Dict[str, Dict[str, Any]]] = Field(None, description="LLM 供應商設定")
    
    # 日記自動刷新設定
    diary_auto_refresh_enabled: Optional[bool] = Field(None, description="是否啟用日記自動刷新")
    diary_auto_refresh_interval_minutes: Optional[int] = Field(None, ge=5, le=1440, description="日記自動刷新間隔（分鐘）")
    
    # 串流 TTL 設定
    default_stream_ttl: Optional[int] = Field(None, ge=30, le=3600, description="預設串流 TTL（秒），範圍：30-3600")


class UserSettingsResponse(BaseModel):
    """使用者設定回應"""
    settings: UserSettings = Field(..., description="使用者設定")
    message: str = Field(default="設定已更新", description="回應訊息")


# ====== 時區工具函數 ======

def get_available_timezones() -> List[str]:
    """獲取所有可用的時區列表"""
    return sorted(pytz.all_timezones)


def get_common_timezones() -> List[Dict[str, str]]:
    """獲取常用時區列表"""
    common_tz = [
        ("Asia/Taipei", "台北時間 (UTC+8)"),
        ("Asia/Shanghai", "北京時間 (UTC+8)"),
        ("Asia/Tokyo", "東京時間 (UTC+9)"),
        ("Asia/Seoul", "首爾時間 (UTC+9)"),
        ("America/New_York", "紐約時間 (UTC-5/-4)"),
        ("America/Los_Angeles", "洛杉磯時間 (UTC-8/-7)"),
        ("Europe/London", "倫敦時間 (UTC+0/+1)"),
        ("Europe/Paris", "巴黎時間 (UTC+1/+2)"),
        ("Australia/Sydney", "雪梨時間 (UTC+10/+11)"),
        ("UTC", "協調世界時 (UTC+0)"),
    ]
    
    return [{"value": tz[0], "label": tz[1]} for tz in common_tz]


def format_datetime_with_timezone(dt: datetime, timezone_str: str) -> str:
    """格式化日期時間並顯示時區"""
    try:
        tz = pytz.timezone(timezone_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local_dt = dt.astimezone(tz)
        return local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
