# -*- coding: utf-8 -*-
"""
測試使用者設定和時區功能
"""
import pytest
from datetime import datetime, timezone
import pytz

from services.APIServer.app.router.User.settings import (
    UserSettings,
    LLMProviderConfig,
    LLMModelAPIConfig,
    get_default_user_settings,
    create_user_settings_with_llm_config
)


def test_default_user_settings():
    """測試預設使用者設定"""
    settings = get_default_user_settings()
    
    assert settings.timezone == "Asia/Taipei"
    assert settings.default_llm_provider == "google"
    assert settings.default_llm_model == "gemini-2.0-flash-exp"
    assert settings.language == "zh-TW"
    assert settings.theme == "light"
    assert settings.notifications_enabled == True


def test_timezone_conversion():
    """測試時區轉換功能"""
    settings = get_default_user_settings()
    
    # 測試 UTC 到使用者時區轉換
    utc_time = datetime(2025, 1, 21, 12, 0, 0, tzinfo=timezone.utc)
    user_time = settings.convert_utc_to_user_timezone(utc_time)
    
    # 台北時間應該是 UTC+8
    expected_hour = 20  # 12 + 8
    assert user_time.hour == expected_hour
    assert user_time.tzinfo.zone == "Asia/Taipei"


def test_llm_config():
    """測試 LLM 設定功能"""
    # 測試預設設定
    settings = get_default_user_settings()
    provider, model, api_key = settings.get_llm_config()
    
    assert provider == "google"
    assert model == "gemini-2.0-flash-exp"
    assert api_key is None  # 使用系統預設
    
    # 測試自定義 API Key
    custom_settings = create_user_settings_with_llm_config(
        provider="google",
        api_key="test-api-key",
        model_names=["gemini-2.0-flash-exp", "gemini-pro"],
        timezone="Asia/Tokyo"
    )
    
    provider, model, api_key = custom_settings.get_llm_config()
    assert provider == "google"
    assert model == "gemini-2.0-flash-exp"
    assert api_key == "test-api-key"
    assert custom_settings.timezone == "Asia/Tokyo"


def test_llm_provider_config():
    """測試 LLM 供應商設定"""
    config = LLMProviderConfig(
        api_key="test-key",
        model_names=["model1", "model2"]
    )
    
    assert config.api_key == "test-key"
    assert config.model_names == ["model1", "model2"]


def test_llm_model_api_config():
    """測試 LLM 模型 API 設定"""
    api_config = LLMModelAPIConfig()
    
    # 添加供應商
    provider_config = LLMProviderConfig(
        api_key="test-key",
        model_names=["model1"]
    )
    api_config.add_provider("google", provider_config)
    
    # 獲取供應商設定
    retrieved_config = api_config.get_provider_config("google")
    assert retrieved_config is not None
    assert retrieved_config.api_key == "test-key"
    
    # 移除供應商
    api_config.remove_provider("google")
    retrieved_config = api_config.get_provider_config("google")
    assert retrieved_config is None


if __name__ == "__main__":
    # 簡單的測試執行
    print("測試預設使用者設定...")
    test_default_user_settings()
    print("✓ 預設使用者設定測試通過")
    
    print("測試時區轉換...")
    test_timezone_conversion()
    print("✓ 時區轉換測試通過")
    
    print("測試 LLM 設定...")
    test_llm_config()
    print("✓ LLM 設定測試通過")
    
    print("測試 LLM 供應商設定...")
    test_llm_provider_config()
    print("✓ LLM 供應商設定測試通過")
    
    print("測試 LLM 模型 API 設定...")
    test_llm_model_api_config()
    print("✓ LLM 模型 API 設定測試通過")
    
    print("\n所有測試通過！🎉")
