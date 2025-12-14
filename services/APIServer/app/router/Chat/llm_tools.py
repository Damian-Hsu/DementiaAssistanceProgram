# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import threading
from pathlib import Path
import time as time_module
from typing import Optional, Dict, Any, List
from datetime import date, datetime, time, timedelta, timezone

try:
    import google.generativeai as genai
except ImportError:
    raise ImportError("google-generativeai package not installed. Run: pip install google-generativeai")

from ...DataAccess.tables import events as events_table
from ...DataAccess.tables import recordings as recordings_table
from .DTO import FunctionCallResult, EventSimple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, exists
from .tools_schema import (
    SEARCH_EVENTS_BY_TIME_TOOL, SEARCH_EVENTS_BY_LOCATION_TOOL, SEARCH_EVENTS_BY_ACTIVITY_TOOL,
    GET_DAILY_SUMMARY_TOOL, SEARCH_RECORDINGS_BY_ACTIVITY_TOOL,
    GET_DIARY_TOOL, REFRESH_DIARY_TOOL, SEARCH_VLOGS_BY_DATE_TOOL
)

# ====== 全域變數 ======
HERE = Path(__file__).resolve().parent           # .../Chat
PROMPTS_DIR = HERE / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system_instruction.md"


# 系統提示詞
with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
        SYSTEM_INSTRUCTION = f.read()
# LLM 模型設定
# 注意：系統預設 API Key 應由呼叫方（例如 Chat/service.py）從 settings 表取得並傳入，
# 此檔案不應直接讀取環境變數或資料庫。


# 所有工具列表
ALL_TOOLS = [
    SEARCH_EVENTS_BY_TIME_TOOL,
    SEARCH_EVENTS_BY_LOCATION_TOOL,
    SEARCH_EVENTS_BY_ACTIVITY_TOOL,
    GET_DAILY_SUMMARY_TOOL,
    SEARCH_RECORDINGS_BY_ACTIVITY_TOOL,
    GET_DIARY_TOOL,
    REFRESH_DIARY_TOOL,
    SEARCH_VLOGS_BY_DATE_TOOL,
]


# ====== LLM 模型管理 ======

def _mask_api_key(api_key: Optional[str], show_full: bool = False) -> str:
    """
    安全地顯示 API Key（只顯示部分字符）
    
    Args:
        api_key: API Key 字串或 None
        show_full: 是否顯示完整 API Key（僅用於調試，預設 False）
    
    Returns:
        遮罩後的 API Key 字串
    """
    if not api_key:
        return "None (使用系統預設)"
    
    api_key_str = str(api_key)
    
    # 如果要求顯示完整，直接返回（僅用於調試）
    if show_full:
        return api_key_str
    
    if len(api_key_str) <= 12:
        # 如果 API Key 太短，全部遮罩
        return "*" * len(api_key_str)
    else:
        # 顯示前8個字符和後8個字符，中間用 * 代替（便於識別不同的 API Key）
        return f"{api_key_str[:8]}...{api_key_str[-8:]}"


def _format_api_error(e: Exception, context: str = "") -> str:
    """
    格式化 API 錯誤訊息，顯示完整的錯誤詳情
    
    Args:
        e: 異常對象
        context: 錯誤上下文描述
    
    Returns:
        格式化的錯誤訊息字串
    """
    import traceback
    import sys
    
    error_lines = []
    error_lines.append("=" * 80)
    error_lines.append(f"[API Error] {context}")
    error_lines.append("-" * 80)
    
    # 基本錯誤資訊
    error_lines.append(f"錯誤類型: {type(e).__name__}")
    error_lines.append(f"錯誤訊息: {str(e)}")
    
    # 嘗試獲取異常的所有屬性
    error_lines.append("\n異常屬性:")
    for attr in dir(e):
        if not attr.startswith('_'):
            try:
                value = getattr(e, attr)
                if not callable(value):
                    # 只顯示可序列化的值
                    try:
                        value_str = str(value)
                        # 限制長度，避免過長
                        if len(value_str) > 500:
                            value_str = value_str[:500] + "... (截斷)"
                        error_lines.append(f"  {attr}: {value_str}")
                    except:
                        error_lines.append(f"  {attr}: <無法顯示>")
            except:
                pass
    
    # Google API 特定的錯誤屬性
    if hasattr(e, 'message'):
        error_lines.append(f"\nAPI 錯誤訊息: {e.message}")
    if hasattr(e, 'status_code'):
        error_lines.append(f"HTTP 狀態碼: {e.status_code}")
    if hasattr(e, 'details'):
        error_lines.append(f"錯誤詳情: {e.details}")
    if hasattr(e, 'reason'):
        error_lines.append(f"錯誤原因: {e.reason}")
    if hasattr(e, 'error'):
        error_lines.append(f"錯誤對象: {e.error}")
    
    # 堆疊追蹤
    error_lines.append("\n完整堆疊追蹤:")
    exc_type, exc_value, exc_traceback = sys.exc_info()
    if exc_traceback:
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
        error_lines.extend(tb_lines)
    
    error_lines.append("=" * 80)
    
    return "\n".join(error_lines)


class UserLLMManager:
    """基於使用者 ID 的 LLM 模型管理器，具有自動清理機制"""
    
    def __init__(self, cleanup_interval: int = 600):  # 改為10分鐘清理間隔，減少CPU使用
        self._user_models: Dict[str, Dict[str, Any]] = {}  # {user_id_use_tools: {model, last_access, config}}
        self._lock = threading.RLock()  # 線程安全鎖
        self._cleanup_interval = cleanup_interval
        self._default_provider = "google"
        self._default_model = "gemini-2.5-flash-lite"  # 使用穩定版本，免費層支持
        self._stop_cleanup = False  # 添加停止標記
        
        # 不要在這裡啟動清理線程，改為延遲啟動
        self._cleanup_thread: Optional[threading.Thread] = None
        print(f"[LLM Manager] 管理器已初始化，清理間隔: {self._cleanup_interval}秒")
    
    def _start_cleanup_thread(self):
        """啟動自動清理線程（僅當需要時）"""
        if self._cleanup_thread is not None and self._cleanup_thread.is_alive():
            return  # 已經在運行
        
        self._stop_cleanup = False
        
        def cleanup_worker():
            while not self._stop_cleanup:
                try:
                    time_module.sleep(self._cleanup_interval)
                    if not self._stop_cleanup:  # 再次檢查
                        self._cleanup_expired_models()
                except Exception as e:
                    print(f"[LLM Manager Cleanup Error] {str(e)}")
            print("[LLM Manager] 清理線程已停止")
        
        self._cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
        self._cleanup_thread.start()
        print(f"[LLM Manager] 自動清理線程已啟動，清理間隔: {self._cleanup_interval}秒")
    
    def _cleanup_expired_models(self):
        """清理過期的模型實例"""
        with self._lock:
            current_time = time_module.time()
            expired_users = []
            
            for user_id, model_info in self._user_models.items():
                last_access = model_info.get('last_access', 0)
                # 改為清理間隔的2倍才清理，給更多緩衝
                if current_time - last_access > (self._cleanup_interval * 2):
                    expired_users.append(user_id)
            
            for user_id in expired_users:
                del self._user_models[user_id]
                print(f"[LLM Manager] 清理過期模型實例: user_id={user_id}")
    
    def shutdown(self):
        """優雅關閉管理器"""
        print("[LLM Manager] 正在關閉管理器...")
        self._stop_cleanup = True
        
        # 等待清理線程退出
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)
        
        # 清理所有模型
        with self._lock:
            self._user_models.clear()
        
        print("[LLM Manager] 管理器已關閉")
    
    def get_model(self, user_id: int, provider: str = "google", api_key: Optional[str] = None, model_name: Optional[str] = None, use_tools: bool = True):
        """獲取使用者的 LLM 模型實例
        
        Args:
            user_id: 使用者 ID
            provider: 供應商名稱
            api_key: API Key
            model_name: 模型名稱
            use_tools: 是否使用工具（Function Calling），預設 True
        """
        # 延遲啟動清理線程
        self._start_cleanup_thread()
        
        with self._lock:
            # 使用預設值
            # 如果 api_key 為 None 或空字串，則為 None（交給 _create_google_model 處理）
            if not api_key:
                api_key = None
            if not model_name:
                model_name = self._default_model
            
            # 為不同用途創建不同的模型實例（使用 tools 與否）
            # 使用 user_id 和 use_tools 作為鍵的一部分
            model_key = f"{user_id}_{use_tools}"
            
            # 檢查是否已有該使用者的模型實例
            if model_key in self._user_models:
                model_info = self._user_models[model_key]
                saved_api_key = model_info['config']['api_key']
                # 標準化 API Key 用於比較（None 和空字串視為相同）
                saved_api_key_normalized = saved_api_key if saved_api_key else None
                api_key_normalized = api_key if api_key else None
                
                # 檢查配置是否相同
                if (model_info['config']['provider'] == provider and 
                    saved_api_key_normalized == api_key_normalized and 
                    model_info['config']['model_name'] == model_name and
                    model_info['config']['use_tools'] == use_tools):
                    # 更新最後訪問時間
                    model_info['last_access'] = time_module.time()
                    return model_info['model']
                else:
                    # 配置不同，需要重新創建
                    old_api_key_display = _mask_api_key(saved_api_key)
                    new_api_key_display = _mask_api_key(api_key)
                    print(f"[LLM Manager] 使用者 {user_id} 配置變更，重新創建模型 (use_tools={use_tools})")
                    print(f"[LLM Manager]   舊配置: provider={model_info['config']['provider']}, model={model_info['config']['model_name']}, use_tools={model_info['config']['use_tools']}, API Key: {old_api_key_display}")
                    print(f"[LLM Manager]   新配置: provider={provider}, model={model_name}, use_tools={use_tools}, API Key: {new_api_key_display}")
            
            # 創建新的模型實例
            try:
                model = self._create_model(provider, api_key, model_name, use_tools=use_tools)
                self._user_models[model_key] = {
                    'model': model,
                    'last_access': time_module.time(),
                    'config': {
                        'provider': provider,
                        'api_key': api_key,
                        'model_name': model_name,
                        'use_tools': use_tools
                    }
                }
                # 顯示 API Key（遮罩後）
                api_key_display = _mask_api_key(api_key)
                tools_status = "with tools" if use_tools else "without tools"
                print(f"[LLM Manager] 為使用者 {user_id} 創建新模型實例: {provider}/{model_name} ({tools_status}), API Key: {api_key_display}")
                return model
            except Exception as e:
                error_msg = _format_api_error(
                    e,
                    f"為使用者 {user_id} 創建模型實例時發生錯誤 (provider={provider}, model={model_name}, use_tools={use_tools})"
                )
                print(error_msg)
                raise
    
    def _create_model(self, provider: str, api_key: str, model_name: str, use_tools: bool = True):
        """創建 LLM 模型實例
        
        Args:
            provider: 供應商名稱
            api_key: API Key
            model_name: 模型名稱
            use_tools: 是否使用工具（Function Calling），預設 True
        """
        if provider == "google":
            return self._create_google_model(api_key, model_name, use_tools=use_tools)
        else:
            raise ValueError(f"不支援的 LLM 供應商: {provider}")
    
    def _create_google_model(self, api_key: str, model_name: str, use_tools: bool = True):
        """創建 Google Gemini 模型
        
        Args:
            api_key: API Key
            model_name: 模型名稱
            use_tools: 是否使用工具（Function Calling），預設 True
        """
        if not api_key:
            raise ValueError("Google API Key 未提供（請在系統設定或使用者設定中配置）")
        
        try:
            genai.configure(api_key=api_key)
        except Exception as config_error:
            error_msg = _format_api_error(
                config_error,
                f"配置 Google API 時發生錯誤 (model={model_name}, use_tools={use_tools})"
            )
            print(error_msg)
            raise
        
        # 根據是否需要工具來決定模型配置
        try:
            if use_tools:
                return genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=ALL_TOOLS,
                )
            else:
                # 不使用工具時，不設定 system_instruction 和 tools，減少 token 使用
                return genai.GenerativeModel(
                    model_name=model_name,
                )
        except Exception as model_error:
            error_msg = _format_api_error(
                model_error,
                f"創建 Google Gemini 模型時發生錯誤 (model={model_name}, use_tools={use_tools})"
            )
            print(error_msg)
            raise
    
    def get_stats(self) -> Dict[str, Any]:
        """獲取管理器統計資訊"""
        with self._lock:
            current_time = time_module.time()
            active_users = []
            user_ids_seen = set()
            
            for model_key, model_info in self._user_models.items():
                # 從 model_key 中提取 user_id (格式: "user_id_use_tools")
                user_id_str = model_key.split('_')[0]
                try:
                    user_id = int(user_id_str)
                except ValueError:
                    continue
                
                if user_id not in user_ids_seen:
                    user_ids_seen.add(user_id)
                last_access = model_info.get('last_access', 0)
                time_since_access = current_time - last_access
                active_users.append({
                    'user_id': user_id,
                    'provider': model_info['config']['provider'],
                    'model_name': model_info['config']['model_name'],
                    'last_access': last_access,
                    'time_since_access': time_since_access,
                    # 由於此模組不再讀取系統預設 API Key，無法判斷是否為「自訂」；
                    # 僅回傳是否有提供 api_key（避免誤判）。
                    'has_api_key': bool(model_info['config'].get('api_key'))
                })
            
            return {
                'total_active_models': len(self._user_models),
                'total_active_users': len(user_ids_seen),
                'cleanup_interval': self._cleanup_interval,
                'active_users': active_users
            }
    
    def force_cleanup_user(self, user_id: int) -> bool:
        """強制清理特定使用者的模型實例（包括所有 use_tools 變體）"""
        with self._lock:
            keys_to_remove = [key for key in self._user_models.keys() if key.startswith(f"{user_id}_")]
            if keys_to_remove:
                for key in keys_to_remove:
                    del self._user_models[key]
                print(f"[LLM Manager] 強制清理使用者 {user_id} 的 {len(keys_to_remove)} 個模型實例")
                return True
            return False


# 全域使用者模型管理器實例
user_llm_manager = UserLLMManager()


# ====== 工具函數實現 ======

async def search_events_by_time(
    db: AsyncSession,
    user_id: int,
    date_from: str,
    date_to: Optional[str] = None,
    limit: int = 10,
    user_timezone: str = "Asia/Taipei"
) -> List[Dict[str, Any]]:
    """按時間範圍查詢事件（支援使用者時區）"""
    try:
        from_date = date.fromisoformat(date_from)
        to_date = date.fromisoformat(date_to) if date_to else from_date
    except ValueError:
        return []
    
    # 將使用者時區的日期轉換為 UTC 時間範圍
    import pytz
    user_tz = pytz.timezone(user_timezone)
    
    # 使用者時區的開始時間（00:00:00）
    from_datetime_user = user_tz.localize(datetime.combine(from_date, time.min))
    # 使用者時區的結束時間（23:59:59.999999）
    to_datetime_user = user_tz.localize(datetime.combine(to_date, time.max))
    
    # 轉換為 UTC 進行資料庫查詢
    from_datetime = from_datetime_user.astimezone(timezone.utc)
    to_datetime = to_datetime_user.astimezone(timezone.utc)
    
    conditions = [
        events_table.Table.user_id == user_id,
        events_table.Table.start_time >= from_datetime,
        events_table.Table.start_time <= to_datetime,
    ]
    
    stmt = (
        select(events_table.Table)
        .where(and_(*conditions))
        .order_by(events_table.Table.start_time.asc())
        .limit(limit)
    )
    
    result = await db.execute(stmt)
    events = result.scalars().all()
    
    # 轉換時間為使用者時區
    user_tz = pytz.timezone(user_timezone)
    
    return [
        {
            "id": str(e.id),
            "time": e.start_time.astimezone(user_tz).strftime("%Y-%m-%d %H:%M") if e.start_time else "未知時間",
            "location": e.scene or "未知地點",
            "activity": e.action or "未知活動",
            "summary": e.summary or "無描述",
            "duration": f"{int(e.duration)}秒" if e.duration else "未知時長",
        }
        for e in events
    ]


async def search_events_by_location(
    db: AsyncSession,
    user_id: int,
    location: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 10,
    user_timezone: str = "Asia/Taipei"
) -> List[Dict[str, Any]]:
    """按地點查詢事件（支援使用者時區）"""
    conditions = [
        events_table.Table.user_id == user_id,
        events_table.Table.scene.ilike(f"%{location}%"),
    ]
    
    if date_from:
        try:
            from_date = date.fromisoformat(date_from)
            # 將使用者時區的日期轉換為 UTC
            import pytz
            user_tz = pytz.timezone(user_timezone)
            from_datetime_user = user_tz.localize(datetime.combine(from_date, time.min))
            from_datetime = from_datetime_user.astimezone(timezone.utc)
            conditions.append(events_table.Table.start_time >= from_datetime)
        except ValueError:
            pass
    
    if date_to:
        try:
            to_date = date.fromisoformat(date_to)
            # 將使用者時區的日期轉換為 UTC
            import pytz
            user_tz = pytz.timezone(user_timezone)
            to_datetime_user = user_tz.localize(datetime.combine(to_date, time.max))
            to_datetime = to_datetime_user.astimezone(timezone.utc)
            conditions.append(events_table.Table.start_time <= to_datetime)
        except ValueError:
            pass
    
    stmt = (
        select(events_table.Table)
        .where(and_(*conditions))
        .order_by(events_table.Table.start_time.asc())
        .limit(limit)
    )
    
    result = await db.execute(stmt)
    events = result.scalars().all()
    
    # 轉換時間為使用者時區
    user_tz = pytz.timezone(user_timezone)
    
    return [
        {
            "id": str(e.id),
            "time": e.start_time.astimezone(user_tz).strftime("%Y-%m-%d %H:%M") if e.start_time else "未知時間",
            "location": e.scene or "未知地點",
            "activity": e.action or "未知活動",
            "summary": e.summary or "無描述",
            "duration": f"{int(e.duration)}秒" if e.duration else "未知時長",
        }
        for e in events
    ]


async def search_events_by_activity(
    db: AsyncSession,
    user_id: int,
    activity: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 10,
    user_timezone: str = "Asia/Taipei"
) -> List[Dict[str, Any]]:
    """按活動類型查詢事件（支援使用者時區）"""
    conditions = [
        events_table.Table.user_id == user_id,
        or_(
            events_table.Table.action.ilike(f"%{activity}%"),
            events_table.Table.summary.ilike(f"%{activity}%"),
        ),
    ]
    
    if date_from:
        try:
            from_date = date.fromisoformat(date_from)
            # 將使用者時區的日期轉換為 UTC
            import pytz
            user_tz = pytz.timezone(user_timezone)
            from_datetime_user = user_tz.localize(datetime.combine(from_date, time.min))
            from_datetime = from_datetime_user.astimezone(timezone.utc)
            conditions.append(events_table.Table.start_time >= from_datetime)
        except ValueError:
            pass
    
    if date_to:
        try:
            to_date = date.fromisoformat(date_to)
            # 將使用者時區的日期轉換為 UTC
            import pytz
            user_tz = pytz.timezone(user_timezone)
            to_datetime_user = user_tz.localize(datetime.combine(to_date, time.max))
            to_datetime = to_datetime_user.astimezone(timezone.utc)
            conditions.append(events_table.Table.start_time <= to_datetime)
        except ValueError:
            pass
    
    stmt = (
        select(events_table.Table)
        .where(and_(*conditions))
        .order_by(events_table.Table.start_time.asc())
        .limit(limit)
    )
    
    result = await db.execute(stmt)
    events = result.scalars().all()
    
    # 轉換時間為使用者時區
    user_tz = pytz.timezone(user_timezone)
    
    return [
        {
            "id": str(e.id),
            "time": e.start_time.astimezone(user_tz).strftime("%Y-%m-%d %H:%M") if e.start_time else "未知時間",
            "location": e.scene or "未知地點",
            "activity": e.action or "未知活動",
            "summary": e.summary or "無描述",
            "duration": f"{int(e.duration)}秒" if e.duration else "未知時長",
        }
        for e in events
    ]


async def get_daily_summary(
    db: AsyncSession,
    user_id: int,
    target_date: str,
    user_timezone: str = "Asia/Taipei"
) -> List[Dict[str, Any]]:
    """獲取某天的生活摘要（支援使用者時區）"""
    try:
        day = date.fromisoformat(target_date)
    except ValueError:
        return []
    
    return await search_events_by_time(db, user_id, target_date, target_date, limit=50, user_timezone=user_timezone)


async def search_recordings_by_activity(
    db: AsyncSession,
    user_id: int,
    activity: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 10,
    user_timezone: str = "Asia/Taipei"
) -> List[Dict[str, Any]]:
    """按活動類型查詢影片（支援使用者時區）"""
    conditions = [
        recordings_table.Table.user_id == user_id,
    ]
    
    # 時間範圍條件（支援相對時間）
    if date_from:
        # 先嘗試解析為相對時間
        parsed_date = _parse_relative_date(date_from, user_timezone)
        from_date = None
        if parsed_date:
            from_date = parsed_date
        else:
            try:
                from_date = date.fromisoformat(date_from)
            except ValueError:
                pass
        
        if from_date:
            import pytz
            user_tz = pytz.timezone(user_timezone)
            from_datetime_user = user_tz.localize(datetime.combine(from_date, time.min))
            from_datetime = from_datetime_user.astimezone(timezone.utc)
            conditions.append(recordings_table.Table.start_time >= from_datetime)
    
    if date_to:
        # 先嘗試解析為相對時間
        parsed_date = _parse_relative_date(date_to, user_timezone)
        to_date = None
        if parsed_date:
            to_date = parsed_date
        else:
            try:
                to_date = date.fromisoformat(date_to)
            except ValueError:
                pass
        
        if to_date:
            import pytz
            user_tz = pytz.timezone(user_timezone)
            to_datetime_user = user_tz.localize(datetime.combine(to_date, time.max))
            to_datetime = to_datetime_user.astimezone(timezone.utc)
            conditions.append(recordings_table.Table.start_time <= to_datetime)
    
    # 通過事件表查詢包含該活動的影片
    # 使用 exists 子查詢：查找包含該活動的 recording_id
    event_conditions = [
        events_table.Table.recording_id == recordings_table.Table.id,
        or_(
            events_table.Table.action.ilike(f"%{activity}%"),
            events_table.Table.summary.ilike(f"%{activity}%")
        )
    ]
    
    subq = select(events_table.Table.id).where(and_(*event_conditions))
    conditions.append(exists(subq))
    
    stmt = (
        select(recordings_table.Table)
        .where(and_(*conditions))
        .order_by(recordings_table.Table.start_time.desc())
        .limit(limit)
    )
    
    result = await db.execute(stmt)
    recordings = result.scalars().all()
    
    # 轉換時間為使用者時區
    import pytz
    user_tz = pytz.timezone(user_timezone)
    
    # 為每個 recording 獲取第一個事件的 summary
    recordings_list = []
    for rec in recordings:
        # 查詢該 recording 的第一個 event 的 summary
        stmt_event = (
            select(events_table.Table.summary, events_table.Table.action, events_table.Table.scene)
            .where(events_table.Table.recording_id == rec.id)
            .order_by(events_table.Table.start_time.asc())
            .limit(1)
        )
        result_event = await db.execute(stmt_event)
        event_row = result_event.first()
        
        summary = None
        action = None
        scene = None
        if event_row:
            summary = event_row.summary
            action = event_row.action
            scene = event_row.scene
        
        # 轉換時間
        start_time_user = None
        if rec.start_time:
            if rec.start_time.tzinfo is None:
                rec.start_time = rec.start_time.replace(tzinfo=timezone.utc)
            start_time_user = rec.start_time.astimezone(user_tz)
        
        recordings_list.append({
            "id": str(rec.id),
            "time": start_time_user.strftime("%Y-%m-%d %H:%M") if start_time_user else "未知時間",
            "duration": rec.duration or 0.0,
            "summary": summary or "無描述",
            "action": action,
            "scene": scene,
            "thumbnail_s3_key": rec.thumbnail_s3_key,
        })
    
    return recordings_list


def _parse_relative_date(date_str: Optional[str], user_timezone: str = "Asia/Taipei") -> Optional[date]:
    """
    解析相對時間或日期字串為 date 對象
    支持：
    - 絕對日期：YYYY-MM-DD
    - 相對時間：今天、昨天、三天前、一週前等
    """
    if not date_str:
        return None
    
    date_str = date_str.strip()
    
    # 嘗試解析為 ISO 格式日期
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        pass
    
    # 解析相對時間
    import pytz
    user_tz = pytz.timezone(user_timezone)
    now_user = datetime.now(timezone.utc).astimezone(user_tz)
    today = now_user.date()
    
    # 常見相對時間
    relative_map = {
        "今天": 0,
        "今日": 0,
        "昨天": -1,
        "昨日": -1,
        "前天": -2,
        "大前天": -3,
    }
    
    if date_str in relative_map:
        days_offset = relative_map[date_str]
        return today + timedelta(days=days_offset)
    
    # 解析「N天前」格式
    import re
    match = re.match(r'(\d+)天前', date_str)
    if match:
        days = int(match.group(1))
        return today + timedelta(days=-days)
    
    # 解析「N週前」格式
    match = re.match(r'(\d+)週前', date_str)
    if match:
        weeks = int(match.group(1))
        return today + timedelta(weeks=-weeks)
    
    # 解析「N個月前」格式（簡化為30天）
    match = re.match(r'(\d+)個月前', date_str)
    if match:
        months = int(match.group(1))
        return today + timedelta(days=-months * 30)
    
    # 如果無法解析，返回 None
    return None


async def get_diary(
    db: AsyncSession,
    user_id: int,
    date_str: Optional[str] = None,
    user_timezone: str = "Asia/Taipei"
) -> Dict[str, Any]:
    """查詢日記（支援相對時間）"""
    from ...DataAccess.tables import diary as diary_table
    
    # 解析日期
    if date_str:
        target_date = _parse_relative_date(date_str, user_timezone)
        if not target_date:
            # 如果無法解析，嘗試使用今天
            import pytz
            user_tz = pytz.timezone(user_timezone)
            now_user = datetime.now(timezone.utc).astimezone(user_tz)
            target_date = now_user.date()
    else:
        # 預設為今天
        import pytz
        user_tz = pytz.timezone(user_timezone)
        now_user = datetime.now(timezone.utc).astimezone(user_tz)
        target_date = now_user.date()
    
    # 查詢日記
    stmt = select(diary_table.Table).where(
        and_(
            diary_table.Table.user_id == user_id,
            diary_table.Table.diary_date == target_date
        )
    )
    result = await db.execute(stmt)
    diary_entry = result.scalar_one_or_none()
    
    if not diary_entry or not diary_entry.content:
        return {
            "date": target_date.isoformat(),
            "content": None,
            "exists": False
        }
    
    return {
        "date": target_date.isoformat(),
        "content": diary_entry.content,
        "exists": True
    }


async def refresh_diary(
    db: AsyncSession,
    user_id: int,
    date_str: Optional[str] = None,
    user_timezone: str = "Asia/Taipei"
) -> Dict[str, Any]:
    """刷新日記（支援相對時間）"""
    from ...router.Chat.service import generate_diary_summary
    from ...router.Chat.DTO import DiarySummaryRequest
    
    # 解析日期
    if date_str:
        target_date = _parse_relative_date(date_str, user_timezone)
        if not target_date:
            import pytz
            user_tz = pytz.timezone(user_timezone)
            now_user = datetime.now(timezone.utc).astimezone(user_tz)
            target_date = now_user.date()
    else:
        import pytz
        user_tz = pytz.timezone(user_timezone)
        now_user = datetime.now(timezone.utc).astimezone(user_tz)
        target_date = now_user.date()
    
    # 調用日記生成 API
    request = DiarySummaryRequest(
        diary_date=target_date,
        force_refresh=True
    )
    
    # 需要獲取 current_user，這裡我們需要從 db 獲取
    from ...DataAccess.tables import users
    user_obj = await db.get(users.Table, user_id)
    if not user_obj:
        return {
            "date": target_date.isoformat(),
            "success": False,
            "message": "用戶不存在"
        }
    
    # 直接調用內部函數
    from .service import _generate_diary_summary
    # 使用本文件中的 search_events_by_time 函數
    
    # 獲取事件
    date_iso = target_date.isoformat()
    events = await search_events_by_time(
        db=db,
        user_id=user_id,
        date_from=date_iso,
        date_to=date_iso,
        limit=100,
        user_timezone=user_timezone
    )
    
    # 生成日記
    try:
        content = await _generate_diary_summary(
            events=events,
            user_id=user_id,
            user_timezone=user_timezone,
            db=db
        )
        
        # 保存到資料庫
        from ...DataAccess.tables import diary as diary_table
        stmt = select(diary_table.Table).where(
            and_(
                diary_table.Table.user_id == user_id,
                diary_table.Table.diary_date == target_date
            )
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            existing.content = content
            await db.commit()
            await db.refresh(existing)
        else:
            new_diary = diary_table.Table(
                user_id=user_id,
                diary_date=target_date,
                content=content
            )
            db.add(new_diary)
            await db.commit()
            await db.refresh(new_diary)
        
        return {
            "date": target_date.isoformat(),
            "success": True,
            "content": content
        }
    except Exception as e:
        return {
            "date": target_date.isoformat(),
            "success": False,
            "message": str(e)
        }


async def search_vlogs_by_date(
    db: AsyncSession,
    user_id: int,
    date_str: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 10,
    user_timezone: str = "Asia/Taipei"
) -> List[Dict[str, Any]]:
    """查詢 Vlog（支援相對時間和日期範圍）"""
    from ...DataAccess.tables import vlogs as vlogs_table
    
    conditions = [
        vlogs_table.Table.user_id == user_id,
    ]
    
    # 如果指定了單個日期
    if date_str and not date_from and not date_to:
        target_date = _parse_relative_date(date_str, user_timezone)
        if target_date:
            conditions.append(vlogs_table.Table.target_date == target_date)
    # 如果指定了日期範圍
    elif date_from or date_to:
        if date_from:
            from_date = _parse_relative_date(date_from, user_timezone)
            if from_date:
                conditions.append(vlogs_table.Table.target_date >= from_date)
        if date_to:
            to_date = _parse_relative_date(date_to, user_timezone)
            if to_date:
                conditions.append(vlogs_table.Table.target_date <= to_date)
    # 如果都沒有指定，預設查詢今天
    else:
        import pytz
        user_tz = pytz.timezone(user_timezone)
        now_user = datetime.now(timezone.utc).astimezone(user_tz)
        today = now_user.date()
        conditions.append(vlogs_table.Table.target_date == today)
    
    stmt = (
        select(vlogs_table.Table)
        .where(and_(*conditions))
        .order_by(vlogs_table.Table.target_date.desc(), vlogs_table.Table.created_at.desc())
        .limit(limit)
    )
    
    result = await db.execute(stmt)
    vlogs_list = result.scalars().all()
    
    # 轉換為字典格式
    vlogs_result = []
    for v in vlogs_list:
        vlogs_result.append({
            "id": str(v.id),
            "title": v.title,
            "date": v.target_date.isoformat() if v.target_date else None,
            "status": v.status,
            "duration": v.duration,
            "thumbnail_s3_key": v.thumbnail_s3_key,
        })
    
    return vlogs_result


# ====== Function Calling 調度器 ======

async def execute_function_call(
    function_name: str,
    arguments: Dict[str, Any],
    db: AsyncSession,
    user_id: int,
    user_timezone: str = "Asia/Taipei"
) -> Any:
    """執行函數調用（支援使用者時區）"""
    if function_name == "search_events_by_time":
        return await search_events_by_time(
            db=db,
            user_id=user_id,
            date_from=arguments.get("date_from"),
            date_to=arguments.get("date_to"),
            limit=arguments.get("limit", 10),
            user_timezone=user_timezone,
        )
    
    elif function_name == "search_events_by_location":
        return await search_events_by_location(
            db=db,
            user_id=user_id,
            location=arguments.get("location"),
            date_from=arguments.get("date_from"),
            date_to=arguments.get("date_to"),
            limit=arguments.get("limit", 10),
            user_timezone=user_timezone,
        )
    
    elif function_name == "search_events_by_activity":
        return await search_events_by_activity(
            db=db,
            user_id=user_id,
            activity=arguments.get("activity"),
            date_from=arguments.get("date_from"),
            date_to=arguments.get("date_to"),
            limit=arguments.get("limit", 10),
            user_timezone=user_timezone,
        )
    
    elif function_name == "get_daily_summary":
        return await get_daily_summary(
            db=db,
            user_id=user_id,
            target_date=arguments.get("date"),
            user_timezone=user_timezone,
        )
    
    elif function_name == "search_recordings_by_activity":
        return await search_recordings_by_activity(
            db=db,
            user_id=user_id,
            activity=arguments.get("activity"),
            date_from=arguments.get("date_from"),
            date_to=arguments.get("date_to"),
            limit=arguments.get("limit", 10),
            user_timezone=user_timezone,
        )
    
    elif function_name == "get_diary":
        return await get_diary(
            db=db,
            user_id=user_id,
            date_str=arguments.get("date"),
            user_timezone=user_timezone,
        )
    
    elif function_name == "refresh_diary":
        return await refresh_diary(
            db=db,
            user_id=user_id,
            date_str=arguments.get("date"),
            user_timezone=user_timezone,
        )
    
    elif function_name == "search_vlogs_by_date":
        return await search_vlogs_by_date(
            db=db,
            user_id=user_id,
            date_str=arguments.get("date"),
            date_from=arguments.get("date_from"),
            date_to=arguments.get("date_to"),
            limit=arguments.get("limit", 10),
            user_timezone=user_timezone,
        )
    
    else:
        return {"error": f"Unknown function: {function_name}"}


# ====== LLM 對話處理 ======

async def process_chat_with_llm(
    model,
    history_messages: List[Dict[str, Any]],
    user_message: str,
    db: AsyncSession,
    user_id: int,
    user_timezone: str = "Asia/Taipei",
    max_iterations: int = 5
) -> tuple[str, List[FunctionCallResult], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], dict]:
    """處理與 LLM 的對話，包括 Function Calling（支援使用者時區）"""
    from ...utils.llm_usage import extract_usage_from_response
    
    # 開始對話
    chat = model.start_chat(history=history_messages[:-1])
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    
    # 發送用戶訊息
    try:
        response = chat.send_message(history_messages[-1]["parts"][0])
        u = extract_usage_from_response(response)
        usage_total["prompt_tokens"] += u["prompt_tokens"]
        usage_total["completion_tokens"] += u["completion_tokens"]
        usage_total["total_tokens"] += u["total_tokens"]
    except Exception as api_error:
        # 處理 Google API 錯誤，顯示完整的錯誤訊息
        error_msg = _format_api_error(
            api_error,
            f"發送訊息給 LLM 時發生錯誤 (user_id={user_id})"
        )
        print(error_msg)
        
        error_message = str(api_error)
        
        # 配額超限錯誤
        if "429" in error_message or "Quota exceeded" in error_message or "RATE_LIMIT_EXCEEDED" in error_message:
            raise ValueError("AI 服務請求過於頻繁，請稍後再試。(API 配額限制)")
        # API 密鑰錯誤
        elif "401" in error_message or "UNAUTHENTICATED" in error_message:
            raise ValueError("AI 服務認證失敗，請聯繫管理員。")
        # 其他 API 錯誤
        else:
            raise ValueError("AI 服務暫時不可用，請稍後再試。")
    
    # 處理 Function Calling
    function_calls_made = []
    all_events = []
    all_recordings = []
    all_diaries = []
    all_vlogs = []
    
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        
        # 檢查是否有函數調用
        if not response.candidates:
            break
        
        candidate = response.candidates[0]
        
        if not hasattr(candidate.content, 'parts'):
            break
        
        has_function_call = False
        
        for part in candidate.content.parts:
            if hasattr(part, 'function_call') and part.function_call:
                has_function_call = True
                fc = part.function_call
                
                # 解析函數參數
                args = {}
                if hasattr(fc, 'args') and fc.args:
                    args = dict(fc.args)
                
                # 執行函數
                try:
                    print(f"[Function Call] 調用函數: {fc.name}, 參數: {args}")
                    result = await execute_function_call(
                        function_name=fc.name,
                        arguments=args,
                        db=db,
                        user_id=user_id,
                        user_timezone=user_timezone
                    )
                    print(f"[Function Call] 函數 {fc.name} 返回結果: type={type(result)}, length={len(result) if isinstance(result, list) else 'N/A'}")
                    
                    # 記錄函數調用
                    function_calls_made.append(
                        FunctionCallResult(
                            function_name=fc.name,
                            arguments=args,
                            result=result
                        )
                    )
                    
                    # 收集事件、影片、日記和Vlog
                    if isinstance(result, list) and len(result) > 0:
                        # 判斷是事件、影片還是Vlog
                        first_item = result[0]
                        print(f"[Function Call Result] function={fc.name}, result_type=list, first_item_keys={list(first_item.keys()) if isinstance(first_item, dict) else 'not_dict'}")
                        
                        if "location" in first_item:
                            # 這是事件列表
                            print(f"[Function Call Result] 識別為事件列表，數量={len(result)}")
                            all_events.extend(result)
                        elif "duration" in first_item and isinstance(first_item.get("duration"), (int, float)) and "date" not in first_item:
                            # 這是影片列表（有duration但沒有date欄位）
                            print(f"[Function Call Result] 識別為影片列表，數量={len(result)}")
                            all_recordings.extend(result)
                        elif "date" in first_item and "status" in first_item:
                            # 這是Vlog列表
                            print(f"[Function Call Result] 識別為Vlog列表，數量={len(result)}")
                            all_vlogs.extend(result)
                        else:
                            # 預設當作事件處理
                            print(f"[Function Call Result] 預設識別為事件列表，數量={len(result)}")
                            all_events.extend(result)
                    elif isinstance(result, dict):
                        # 判斷是日記還是其他字典結果
                        if "content" in result or "exists" in result:
                            # 這是日記結果
                            all_diaries.append(result)
                        elif "success" in result:
                            # 這是刷新日記的結果
                            all_diaries.append(result)
                    
                    # 將結果返回給 LLM（加入錯誤處理）
                    try:
                        response = chat.send_message({
                            "function_response": {
                                "name": fc.name,
                                "response": {"result": result}
                            }
                        })
                        u = extract_usage_from_response(response)
                        usage_total["prompt_tokens"] += u["prompt_tokens"]
                        usage_total["completion_tokens"] += u["completion_tokens"]
                        usage_total["total_tokens"] += u["total_tokens"]
                    except Exception as send_error:
                        # 如果再次調用 LLM 失敗，記錄完整錯誤訊息
                        error_msg = _format_api_error(
                            send_error,
                            f"發送函數調用結果給 LLM 時發生錯誤 (user_id={user_id}, function={fc.name})"
                        )
                        print(error_msg)
                        break
                    
                except Exception as e:
                    # 記錄函數調用錯誤
                    error_msg = _format_api_error(
                        e,
                        f"執行函數調用時發生錯誤 (user_id={user_id}, function={fc.name})"
                    )
                    print(error_msg)
                    
                    # 嘗試返回錯誤給 LLM
                    try:
                        response = chat.send_message({
                            "function_response": {
                                "name": fc.name,
                                "response": {"error": str(e)}
                            }
                        })
                        u = extract_usage_from_response(response)
                        usage_total["prompt_tokens"] += u["prompt_tokens"]
                        usage_total["completion_tokens"] += u["completion_tokens"]
                        usage_total["total_tokens"] += u["total_tokens"]
                    except Exception as send_error:
                        # 如果發送錯誤也失敗，記錄並跳出
                        send_error_msg = _format_api_error(
                            send_error,
                            f"發送函數調用錯誤給 LLM 時發生錯誤 (user_id={user_id}, function={fc.name})"
                        )
                        print(send_error_msg)
                        break
        
        if not has_function_call:
            break
    
    # 獲取最終回覆
    final_message = ""
    if response.candidates:
        candidate = response.candidates[0]
        if hasattr(candidate.content, 'parts'):
            for part in candidate.content.parts:
                if hasattr(part, 'text') and part.text:
                    final_message += part.text
    
    if not final_message:
        final_message = "抱歉，我無法理解您的問題。請試著換個方式描述。"
    
    return final_message, function_calls_made, all_events, all_recordings, all_diaries, all_vlogs, usage_total
