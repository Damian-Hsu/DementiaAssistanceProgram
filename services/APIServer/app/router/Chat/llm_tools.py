# -*- coding: utf-8 -*-
from __future__ import annotations
import os
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
from .DTO import FunctionCallResult, EventSimple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from .tools_schema import SEARCH_EVENTS_BY_TIME_TOOL, SEARCH_EVENTS_BY_LOCATION_TOOL, SEARCH_EVENTS_BY_ACTIVITY_TOOL, GET_DAILY_SUMMARY_TOOL

# ====== 全域變數 ======
HERE = Path(__file__).resolve().parent           # .../Chat
PROMPTS_DIR = HERE / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system_instruction.md"


# 系統提示詞
with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
        SYSTEM_INSTRUCTION = f.read()
# LLM 模型設定
# 定義工具函數（使用字典格式，Gemini SDK 會自動轉換）
DEFAULT_GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")


# 所有工具列表
ALL_TOOLS = [
    SEARCH_EVENTS_BY_TIME_TOOL,
    SEARCH_EVENTS_BY_LOCATION_TOOL,
    SEARCH_EVENTS_BY_ACTIVITY_TOOL,
    GET_DAILY_SUMMARY_TOOL,
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
        self._default_model = "gemini-2.0-flash"  # 使用穩定版本，免費層支持
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
        # 如果沒有提供 API Key，使用系統預設的
        if not api_key:
            api_key = DEFAULT_GOOGLE_API_KEY
            print("[LLM Manager] 使用系統預設的 Google API Key")
        
        if not api_key:
            raise ValueError("Google API Key 未提供（請設定 GOOGLE_API_KEY 環境變數）")
        
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
                    'has_custom_api_key': model_info['config']['api_key'] != DEFAULT_GOOGLE_API_KEY
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
) -> tuple[str, List[FunctionCallResult], List[Dict[str, Any]]]:
    """處理與 LLM 的對話，包括 Function Calling（支援使用者時區）"""
    
    # 開始對話
    chat = model.start_chat(history=history_messages[:-1])
    
    # 發送用戶訊息
    try:
        response = chat.send_message(history_messages[-1]["parts"][0])
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
                    result = await execute_function_call(
                        function_name=fc.name,
                        arguments=args,
                        db=db,
                        user_id=user_id,
                        user_timezone=user_timezone
                    )
                    
                    # 記錄函數調用
                    function_calls_made.append(
                        FunctionCallResult(
                            function_name=fc.name,
                            arguments=args,
                            result=result
                        )
                    )
                    
                    # 收集事件
                    if isinstance(result, list):
                        all_events.extend(result)
                    
                    # 將結果返回給 LLM（加入錯誤處理）
                    try:
                        response = chat.send_message({
                            "function_response": {
                                "name": fc.name,
                                "response": {"result": result}
                            }
                        })
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
    
    return final_message, function_calls_made, all_events
