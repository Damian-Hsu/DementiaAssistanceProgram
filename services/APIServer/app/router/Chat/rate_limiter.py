# -*- coding: utf-8 -*-
"""
簡單的內存速率限制器和請求緩存
用於緩解 Google Gemini API 配額限制問題
"""
from __future__ import annotations
import time
import hashlib
from typing import Optional, Dict, Any
from collections import deque
from datetime import datetime, timedelta


class RateLimiter:
    """
    簡單的滑動窗口速率限制器
    
    Google Gemini API 免費版限制：
    - 每分鐘 5 次請求 (RPM)
    - 每日 25 次請求 (RPD)
    """
    
    def __init__(self, rpm: int = 10, rpd: int = 20):
        """
        初始化速率限制器
        
        Args:
            rpm: 每分鐘請求數限制（設為 10）
            rpd: 每日請求數限制（設為 20 保留緩衝）
        """
        self.rpm = rpm
        self.rpd = rpd
        
        # 滑動窗口記錄（分鐘級別）
        self.minute_window: deque = deque(maxlen=rpm * 2)
        
        # 每日計數器
        self.daily_count = 0
        self.daily_reset_time = datetime.now() + timedelta(days=1)
    
    def check_and_update(self, user_id: int) -> tuple[bool, Optional[str]]:
        """
        檢查是否可以發送請求，並更新計數器
        
        Returns:
            (是否允許, 錯誤訊息)
        """
        now = time.time()
        
        # 重置每日計數器
        if datetime.now() >= self.daily_reset_time:
            self.daily_count = 0
            self.daily_reset_time = datetime.now() + timedelta(days=1)
        
        # 檢查每日限制
        if self.daily_count >= self.rpd:
            remaining_time = (self.daily_reset_time - datetime.now()).total_seconds()
            hours = int(remaining_time // 3600)
            minutes = int((remaining_time % 3600) // 60)
            return False, f"今日 API 配額已用完，請在 {hours} 小時 {minutes} 分鐘後再試。"
        
        # 移除 1 分鐘前的記錄
        one_minute_ago = now - 60
        while self.minute_window and self.minute_window[0] < one_minute_ago:
            self.minute_window.popleft()
        
        # 檢查每分鐘限制
        if len(self.minute_window) >= self.rpm:
            wait_time = int(60 - (now - self.minute_window[0]))
            return False, f"請求過於頻繁，請等待 {wait_time} 秒後再試。"
        
        # 允許請求，更新計數器
        self.minute_window.append(now)
        self.daily_count += 1
        
        return True, None
    
    def get_stats(self) -> Dict[str, Any]:
        """獲取當前統計資訊"""
        now = time.time()
        one_minute_ago = now - 60
        recent_requests = sum(1 for t in self.minute_window if t >= one_minute_ago)
        
        return {
            "rpm_used": recent_requests,
            "rpm_limit": self.rpm,
            "daily_used": self.daily_count,
            "daily_limit": self.rpd,
            "daily_reset_in": int((self.daily_reset_time - datetime.now()).total_seconds()),
        }


class RequestCache:
    """
    簡單的請求緩存
    相同的查詢在短時間內會返回緩存結果
    """
    
    def __init__(self, ttl: int = 300):
        """
        初始化緩存
        
        Args:
            ttl: 緩存生存時間（秒），默認 5 分鐘
        """
        self.ttl = ttl
        self.cache: Dict[str, tuple[Any, float]] = {}
    
    def _make_key(self, user_id: int, message: str, **kwargs) -> str:
        """生成緩存鍵"""
        # 將所有參數組合成字串並生成哈希
        key_str = f"{user_id}:{message}:{sorted(kwargs.items())}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get(self, user_id: int, message: str, **kwargs) -> Optional[Any]:
        """獲取緩存"""
        key = self._make_key(user_id, message, **kwargs)
        
        if key in self.cache:
            result, timestamp = self.cache[key]
            
            # 檢查是否過期
            if time.time() - timestamp < self.ttl:
                return result
            else:
                # 過期則刪除
                del self.cache[key]
        
        return None
    
    def set(self, user_id: int, message: str, result: Any, **kwargs):
        """設置緩存"""
        key = self._make_key(user_id, message, **kwargs)
        self.cache[key] = (result, time.time())
    
    def clear_expired(self):
        """清除過期緩存"""
        now = time.time()
        expired_keys = [
            k for k, (_, timestamp) in self.cache.items()
            if now - timestamp >= self.ttl
        ]
        for k in expired_keys:
            del self.cache[k]
    
    def get_stats(self) -> Dict[str, Any]:
        """獲取緩存統計"""
        now = time.time()
        valid_count = sum(
            1 for _, timestamp in self.cache.values()
            if now - timestamp < self.ttl
        )
        return {
            "total_cached": len(self.cache),
            "valid_cached": valid_count,
            "ttl": self.ttl,
        }


# 全局實例（單例模式）
_rate_limiter = RateLimiter(rpm=10, rpd=20)
_request_cache = RequestCache(ttl=300)


def get_rate_limiter() -> RateLimiter:
    """獲取速率限制器實例"""
    return _rate_limiter


def get_request_cache() -> RequestCache:
    """獲取請求緩存實例"""
    return _request_cache

