# -*- coding: utf-8 -*-
"""
簡單的內存速率限制器（per-user）。

注意：
- 只應用在「使用系統預設 AI API Key」的情況，避免把使用者自帶 key 的使用量也算進來。
- 聊天回覆不應做基於「使用者問題」的快取，避免錯誤回覆被重複命中。
"""
from __future__ import annotations
import time
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
        # 預設限制值（可由呼叫端覆寫）
        self.rpm = rpm
        self.rpd = rpd

        # per-user 狀態：user_id -> {minute_window, daily_count, daily_reset_time, last_seen}
        self._users: Dict[int, Dict[str, Any]] = {}

    def _get_user_state(self, user_id: int, rpm: int) -> Dict[str, Any]:
        st = self._users.get(int(user_id))
        now_dt = datetime.now()
        if not st:
            st = {
                "minute_window": deque(maxlen=max(1, rpm * 2)),
                "daily_count": 0,
                "daily_reset_time": now_dt + timedelta(days=1),
                "last_seen": time.time(),
            }
            self._users[int(user_id)] = st
            return st

        # 若 rpm 變更，更新 deque maxlen（保留最近資料）
        mw: deque = st.get("minute_window") or deque()
        desired_maxlen = max(1, rpm * 2)
        if getattr(mw, "maxlen", None) != desired_maxlen:
            new_mw = deque(mw, maxlen=desired_maxlen)
            st["minute_window"] = new_mw

        st["last_seen"] = time.time()
        return st

    def cleanup_inactive(self, max_idle_seconds: int = 3600):
        """清理久未使用的使用者狀態，避免記憶體成長（預設 1 小時）。"""
        now = time.time()
        to_del = [uid for uid, st in self._users.items() if now - float(st.get("last_seen", now)) > max_idle_seconds]
        for uid in to_del:
            self._users.pop(uid, None)
    
    def check_and_update(self, user_id: int, rpm: int | None = None, rpd: int | None = None) -> tuple[bool, Optional[str]]:
        """
        檢查是否可以發送請求，並更新計數器
        
        Returns:
            (是否允許, 錯誤訊息)
        """
        rpm = int(rpm if rpm is not None else self.rpm)
        rpd = int(rpd if rpd is not None else self.rpd)

        now = time.time()
        st = self._get_user_state(int(user_id), rpm=rpm)
        minute_window: deque = st["minute_window"]
        daily_count: int = int(st.get("daily_count", 0))
        daily_reset_time: datetime = st.get("daily_reset_time") or (datetime.now() + timedelta(days=1))

        # 重置每日計數器（per-user）
        if datetime.now() >= daily_reset_time:
            daily_count = 0
            daily_reset_time = datetime.now() + timedelta(days=1)
            st["daily_count"] = daily_count
            st["daily_reset_time"] = daily_reset_time

        # 檢查每日限制（per-user）
        if daily_count >= rpd:
            remaining_time = (daily_reset_time - datetime.now()).total_seconds()
            hours = int(remaining_time // 3600)
            minutes = int((remaining_time % 3600) // 60)
            return False, f"今日 API 配額已用完，請在 {hours} 小時 {minutes} 分鐘後再試。"
        
        # 移除 1 分鐘前的記錄（per-user）
        one_minute_ago = now - 60
        while minute_window and minute_window[0] < one_minute_ago:
            minute_window.popleft()
        
        # 檢查每分鐘限制
        if len(minute_window) >= rpm:
            wait_time = int(60 - (now - minute_window[0]))
            return False, f"請求過於頻繁，請等待 {wait_time} 秒後再試。"
        
        # 允許請求，更新計數器
        minute_window.append(now)
        daily_count += 1
        st["daily_count"] = daily_count

        # 偶爾清理（避免每次都掃）
        if len(self._users) > 2000:
            self.cleanup_inactive(max_idle_seconds=3600)
        
        return True, None
    
    def get_stats(self, user_id: int, rpm: int | None = None, rpd: int | None = None) -> Dict[str, Any]:
        """獲取指定使用者當前統計資訊（per-user）。"""
        rpm = int(rpm if rpm is not None else self.rpm)
        rpd = int(rpd if rpd is not None else self.rpd)

        st = self._get_user_state(int(user_id), rpm=rpm)
        minute_window: deque = st["minute_window"]
        daily_count: int = int(st.get("daily_count", 0))
        daily_reset_time: datetime = st.get("daily_reset_time") or (datetime.now() + timedelta(days=1))

        now = time.time()
        one_minute_ago = now - 60
        recent_requests = sum(1 for t in minute_window if t >= one_minute_ago)

        return {
            "rpm_used": recent_requests,
            "rpm_limit": rpm,
            "daily_used": daily_count,
            "daily_limit": rpd,
            "daily_reset_in": int((daily_reset_time - datetime.now()).total_seconds()),
        }


# 全局實例（單例模式）
_rate_limiter = RateLimiter(rpm=10, rpd=20)


def get_rate_limiter() -> RateLimiter:
    """獲取速率限制器實例"""
    return _rate_limiter

