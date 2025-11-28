# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import json
from typing import Optional, Dict, Any, List
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func

from ...DataAccess.Connect import get_session
from ...DataAccess.tables import events as events_table
from ...DataAccess.tables import diary as diary_table
from ...DataAccess.tables import users
from ...DataAccess.tables.__Enumeration import Role
from ...router.User.service import UserService

from .DTO import (
    ChatRequest,
    ChatResponse,
    ChatMessage,
    FunctionCallResult,
    EventSimple,
    OkResp,
    DiarySummaryRequest,
    DiarySummaryResponse
)

from .rate_limiter import get_rate_limiter, get_request_cache
from .llm_tools import user_llm_manager, process_chat_with_llm, search_events_by_time

# ====== Router 初始化 ======
chat_router = APIRouter(prefix="/chat", tags=["chat"])

# ====== User Service 實例 ======
user_service = UserService()


# ====== API 端點 ======

@chat_router.post("/", response_model=ChatResponse)
async def chat_with_memory_assistant(
    request: Request,
    body: ChatRequest,
    db: AsyncSession = Depends(get_session),
):
    """
    對話式記憶助理（支持 Function Calling）
    
    **功能**：
    - 自然語言對話查詢生活事件
    - 支持多輪對話上下文
    - 自動調用工具函數獲取數據
    - 友善的對話式回覆
    
    **範例對話**：
    ```
    用戶: "我今天幾點吃早餐？"
    AI: "根據記錄，您今天早上 8:30 在廚房吃早餐，大約持續了 15 分鐘。"
    
    用戶: "我吃了什麼？"
    AI: "讓我查一下早餐的詳細資訊... [調用函數] 您吃了麵包和牛奶。"
    ```
    """
    current_user = request.state.current_user
    
    # 獲取速率限制器和緩存
    rate_limiter = get_rate_limiter()
    cache = get_request_cache()
    
    # 1. 檢查速率限制（Admin 免限制）
    is_admin = getattr(current_user, "role", None) == Role.admin
    if not is_admin:
        allowed, error_msg = rate_limiter.check_and_update(current_user.id)
        if not allowed:
            # 獲取統計資訊
            stats = rate_limiter.get_stats()
            detail = f"{error_msg} (已使用: {stats['daily_used']}/{stats['daily_limit']} 次，每分鐘: {stats['rpm_used']}/{stats['rpm_limit']} 次)"
            raise HTTPException(
                status_code=429,
                detail=detail
            )
    
    # 2. 檢查緩存（相同的查詢在 5 分鐘內返回緩存結果）
    cache_key_params = {
        "date_from": str(body.date_from) if body.date_from else None,
        "date_to": str(body.date_to) if body.date_to else None,
    }
    cached_result = cache.get(current_user.id, body.message, **cache_key_params)
    if cached_result:
        print(f"[Cache Hit] user={current_user.id}, message={body.message[:50]}")
        return cached_result
    
    try:
        # 獲取使用者設定
        user_timezone = user_service.get_user_timezone(current_user)
        llm_provider, llm_model, llm_api_key = user_service.get_user_llm_config(current_user)
        
        # 獲取 LLM 模型（使用使用者 ID）
        model = user_llm_manager.get_model(
            user_id=current_user.id,
            provider=llm_provider,
            api_key=llm_api_key,
            model_name=llm_model
        )
        
        # 構建對話歷史
        history_messages = []
        
        # 限制歷史訊息數量（最多保留最近 10 條）
        recent_history = body.history[-10:] if len(body.history) > 10 else body.history
        
        for msg in recent_history:
            history_messages.append({
                "role": msg.role,
                "parts": [msg.content],
            })
        
        # 添加當前用戶訊息
        history_messages.append({
            "role": "user",
            "parts": [body.message],
        })
        
        # 添加上下文信息（使用使用者時區和基本資訊）
        import pytz
        user_tz = pytz.timezone(user_timezone)
        today_utc = datetime.now(timezone.utc)
        today_user = today_utc.astimezone(user_tz)
        today_str = today_user.strftime("%Y-%m-%d")
        
        # 構建使用者基本資訊
        user_info_parts = []
        user_info_parts.append(f"使用者姓名：{current_user.name}")
        user_info_parts.append(f"使用者性別：{'男性' if current_user.gender == 'male' else '女性'}")
        user_info_parts.append(f"使用者時區：{user_timezone}")
        user_info_parts.append(f"當前時間：{today_user.strftime('%Y-%m-%d %H:%M:%S')} ({user_timezone})")
        
        context_message = f"\n\n[系統上下文] 今天是 {today_str} ({user_timezone})。\n[使用者資訊] {', '.join(user_info_parts)}。"
        
        if body.date_from or body.date_to:
            date_range = f"用戶指定查詢範圍：{body.date_from or '不限'} 到 {body.date_to or '不限'}"
            context_message += f" {date_range}。"
        
        # 將上下文附加到最後一條用戶訊息
        history_messages[-1]["parts"][0] += context_message
        
        # 使用新的 LLM 處理函數
        final_message, function_calls_made, all_events, all_recordings, all_diaries, all_vlogs = await process_chat_with_llm(
            model=model,
            history_messages=history_messages,
            user_message=body.message,
            db=db,
            user_id=current_user.id,
            user_timezone=user_timezone,
            max_iterations=5
        )
        
        # 轉換事件為 EventSimple 格式（使用使用者時區）
        event_objects = []
        if all_events:
            # 去重（根據 id）
            seen_ids = set()
            for e in all_events:
                event_id = e.get("id")
                if event_id and event_id not in seen_ids:
                    seen_ids.add(event_id)
                    # 需要從數據庫重新獲取完整的事件對象
                    try:
                        from uuid import UUID
                        stmt = select(events_table.Table).where(
                            events_table.Table.id == UUID(event_id)
                        )
                        result_query = await db.execute(stmt)
                        event_obj = result_query.scalar_one_or_none()
                        if event_obj:
                            # 轉換時間到使用者時區
                            if event_obj.start_time:
                                user_tz = pytz.timezone(user_timezone)
                                if event_obj.start_time.tzinfo is None:
                                    event_obj.start_time = event_obj.start_time.replace(tzinfo=timezone.utc)
                                event_obj.start_time = event_obj.start_time.astimezone(user_tz)
                            
                            event_objects.append(EventSimple.model_validate(event_obj))
                    except Exception as db_error:
                        print(f"[DB Query Error] {str(db_error)}")
                        pass
        
        # 轉換影片為 RecordingSimple 格式
        from .DTO import RecordingSimple, DiarySimple, VlogSimple
        recording_objects = []
        if all_recordings:
            # 去重（根據 id）
            seen_recording_ids = set()
            for r in all_recordings:
                recording_id = r.get("id")
                if recording_id and recording_id not in seen_recording_ids:
                    seen_recording_ids.add(recording_id)
                    try:
                        recording_objects.append(RecordingSimple(**r))
                    except Exception as e:
                        print(f"[Recording Parse Error] {str(e)}")
                        pass
        
        # 轉換日記為 DiarySimple 格式
        diary_objects = []
        if all_diaries:
            for d in all_diaries:
                try:
                    diary_objects.append(DiarySimple(**d))
                except Exception as e:
                    print(f"[Diary Parse Error] {str(e)}")
                    pass
        
        # 轉換Vlog為 VlogSimple 格式
        vlog_objects = []
        if all_vlogs:
            # 去重（根據 id）
            seen_vlog_ids = set()
            for v in all_vlogs:
                vlog_id = v.get("id")
                if vlog_id and vlog_id not in seen_vlog_ids:
                    seen_vlog_ids.add(vlog_id)
                    try:
                        vlog_objects.append(VlogSimple(**v))
                    except Exception as e:
                        print(f"[Vlog Parse Error] {str(e)}")
                        pass
        
        result = ChatResponse(
            message=final_message,
            events=event_objects,
            recordings=recording_objects,
            diaries=diary_objects,
            vlogs=vlog_objects,
            function_calls=function_calls_made,
            has_more=len(all_events) >= body.max_results,
            total_events=len(event_objects),
            total_recordings=len(recording_objects),
            total_diaries=len(diary_objects),
            total_vlogs=len(vlog_objects)
        )
        
        # 3. 將結果存入緩存
        cache.set(current_user.id, body.message, result, **cache_key_params)
        
        return result
    
    except HTTPException:
        # 重新拋出 HTTPException（已經格式化好的錯誤）
        raise
    
    except ValueError as ve:
        # 處理 LLM 相關錯誤
        error_msg = str(ve)
        if "API 配額限制" in error_msg:
            raise HTTPException(status_code=429, detail=error_msg)
        elif "認證失敗" in error_msg:
            raise HTTPException(status_code=500, detail=error_msg)
        else:
            raise HTTPException(status_code=503, detail=error_msg)
    
    except Exception as general_error:
        # 捕獲所有其他未預期的錯誤
        print(f"[Chat Error] {str(general_error)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="對話處理過程中發生錯誤，請稍後再試。"
        )


# ====== 管理端點 ======

@chat_router.delete("/cleanup/{user_id}")
async def force_cleanup_user_model(
    request: Request,
    user_id: int,
):
    """
    強制清理特定使用者的 LLM 模型實例
    
    僅管理員可使用
    """
    current_user = request.state.current_user
    
    # 檢查管理員權限
    if current_user.role != Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="僅管理員可執行此操作"
        )
    
    success = user_llm_manager.force_cleanup_user(user_id)
    
    if success:
        return {"message": f"已清理使用者 {user_id} 的模型實例"}
    else:
        return {"message": f"使用者 {user_id} 沒有活躍的模型實例"}


@chat_router.get("/stats")
async def get_llm_stats(request: Request):
    """
    獲取 LLM API 使用統計
    
    返回速率限制和緩存的統計資訊
    """
    rate_limiter = get_rate_limiter()
    cache = get_request_cache()
    
    # 獲取使用者設定
    current_user = request.state.current_user
    llm_provider, llm_model, llm_api_key = user_service.get_user_llm_config(current_user)
    
    return {
        "rate_limit": rate_limiter.get_stats(),
        "cache": cache.get_stats(),
        "llm_manager": user_llm_manager.get_stats(),
        "api_info": {
            "provider": llm_provider,
            "model": llm_model,
            "has_custom_api_key": llm_api_key is not None,
            "free_tier_limits": {
                "rpm": 5,
                "rpd": 25,
            },
            "configured_limits": {
                "rpm": rate_limiter.rpm,
                "rpd": rate_limiter.rpd,
            }
        }
    }


# ====== 日記摘要功能 ======

def _calculate_events_hash(events: List[Dict[str, Any]]) -> str:
    """計算事件列表的哈希值"""
    import hashlib
    import json
    
    # 將事件轉換為可序列化的格式（只包含關鍵字段）
    event_data = []
    for e in events:
        event_data.append({
            "id": str(e.get("id", "")),
            "time": e.get("time", ""),
            "location": e.get("location", ""),
            "activity": e.get("activity", ""),
            "summary": e.get("summary", ""),
        })
    
    # 按 ID 排序以確保一致性
    event_data.sort(key=lambda x: x["id"])
    
    # 計算 SHA256 哈希
    events_json = json.dumps(event_data, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(events_json.encode('utf-8')).hexdigest()


async def _generate_diary_summary(
    events: List[Dict[str, Any]],
    user_id: int,
    user_timezone: str,
    db: AsyncSession
) -> str:
    """使用 LLM 生成日記摘要"""
    from pathlib import Path
    
    # 讀取 prompt
    HERE = Path(__file__).resolve().parent
    PROMPT_PATH = HERE / "prompts" / "diary_summary.md"
    
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        system_prompt = f.read()
    
    # 構建事件列表文本
    events_text = "\n".join([
        f"- {e.get('time', '未知時間')} | {e.get('location', '未知地點')} | {e.get('activity', '未知活動')} | {e.get('summary', '無描述')}"
        for e in events
    ])
    
    if not events_text:
        return "今天沒有記錄到任何事件。"
    
    # 獲取 LLM 模型
    current_user = await db.get(users.Table, user_id)
    if not current_user:
        raise HTTPException(status_code=404, detail="使用者不存在")
    
    llm_provider, llm_model, llm_api_key = user_service.get_user_llm_config(current_user)
    # 日記摘要不需要 tools，創建一個不帶 tools 的模型實例以減少 token 使用
    model = user_llm_manager.get_model(
        user_id=user_id,
        provider=llm_provider,
        api_key=llm_api_key,
        model_name=llm_model,
        use_tools=False  # 日記摘要不需要 function calling
    )
    
    # 構建提示詞（將 system_prompt 作為用戶訊息的一部分，因為模型沒有設定 system_instruction）
    # 使用 prompt 模板，將事件列表插入到模板中
    user_message = system_prompt.replace("{events_text}", events_text)
    
    try:
        # 調用 LLM
        chat = model.start_chat(history=[])
        response = chat.send_message(user_message)
        
        # 提取回覆
        summary = ""
        if response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate.content, 'parts'):
                for part in candidate.content.parts:
                    if hasattr(part, 'text') and part.text:
                        summary += part.text
        
        # 不再限制長度
        
        return summary.strip() if summary else "今天沒有記錄到任何事件。"
    
    except Exception as e:
        # 使用 UserLLMManager 的錯誤格式化函數顯示完整錯誤
        from .llm_tools import _format_api_error
        error_msg = _format_api_error(
            e,
            f"生成日記摘要時發生錯誤 (user_id={user_id}, events_count={len(events)})"
        )
        print(error_msg)
        
        error_str = str(e)
        
        # 檢查是否為配額限制錯誤
        if "429" in error_str or "quota" in error_str.lower() or "Quota exceeded" in error_str:
            # 提取重試延遲時間（如果有的話）
            import re
            retry_match = re.search(r'retry.*?(\d+)\s*seconds?', error_str, re.IGNORECASE)
            retry_seconds = int(retry_match.group(1)) if retry_match else 60
            
            # 拋出特殊的異常，讓上層處理
            raise HTTPException(
                status_code=429,
                detail=f"AI 服務配額已用盡，請在 {retry_seconds} 秒後再試，或聯繫管理員檢查 API 配額設定。"
            )
        
        # 其他錯誤，返回簡單摘要但不拋出異常
        # 這樣可以讓日記功能在 API 失敗時仍能顯示基本資訊
        return f"今天記錄了 {len(events)} 個事件。由於 AI 服務暫時無法使用，無法生成詳細日記摘要。"


@chat_router.post("/diary/summary", response_model=DiarySummaryResponse)
async def generate_diary_summary(
    request: Request,
    body: DiarySummaryRequest,
    db: AsyncSession = Depends(get_session),
):
    """
    生成或獲取日記摘要
    
    **功能**：
    - 根據指定日期獲取該日的事件
    - 計算事件哈希值，如果與上次相同則不刷新
    - 使用 LLM 生成日記摘要（無字數限制）
    - 保存到資料庫
    
    **參數**：
    - diary_date: 日記日期
    - force_refresh: 是否強制刷新（忽略哈希檢查）
    """
    current_user = request.state.current_user
    user_timezone = user_service.get_user_timezone(current_user)
    
    # 轉換日期為使用者時區
    import pytz
    user_tz = pytz.timezone(user_timezone)
    today_utc = datetime.now(timezone.utc)
    today_user = today_utc.astimezone(user_tz)
    
    # 獲取指定日期的事件
    date_str = body.diary_date.isoformat()
    events = await search_events_by_time(
        db=db,
        user_id=current_user.id,
        date_from=date_str,
        date_to=date_str,
        limit=100,  # 獲取最多 100 個事件
        user_timezone=user_timezone
    )
    
    # 計算事件哈希值
    events_hash = _calculate_events_hash(events)
    
    # 查詢現有日記
    stmt = select(diary_table.Table).where(
        and_(
            diary_table.Table.user_id == current_user.id,
            diary_table.Table.diary_date == body.diary_date
        )
    )
    result = await db.execute(stmt)
    existing_diary = result.scalar_one_or_none()
    
    is_refreshed = False
    
    # 檢查是否需要刷新
    if body.force_refresh or not existing_diary or existing_diary.events_hash != events_hash:
        # 需要刷新
        if len(events) == 0:
            # 沒有事件，返回空內容
            summary_content = "今天沒有記錄到任何事件。"
        else:
            try:
                # 生成摘要
                summary_content = await _generate_diary_summary(
                    events=events,
                    user_id=current_user.id,
                    user_timezone=user_timezone,
                    db=db
                )
            except HTTPException:
                # 如果是 HTTPException（如配額限制），直接重新拋出
                raise
            except Exception as e:
                # 其他錯誤，記錄但不中斷流程
                print(f"[Diary Summary Generation Error] {str(e)}")
                # 如果有現有日記，保留原有內容
                if existing_diary and existing_diary.content:
                    summary_content = existing_diary.content
                    is_refreshed = False  # 沒有真正刷新
                else:
                    # 沒有現有內容，返回簡單摘要
                    summary_content = f"今天記錄了 {len(events)} 個事件。由於 AI 服務暫時無法使用，無法生成詳細日記摘要。"
        
        # 只有在成功生成摘要或沒有事件時才保存
        if summary_content:
            # 保存或更新日記
            if existing_diary:
                existing_diary.content = summary_content
                existing_diary.events_hash = events_hash
                db.add(existing_diary)
            else:
                new_diary = diary_table.Table(
                    user_id=current_user.id,
                    diary_date=body.diary_date,
                    content=summary_content,
                    events_hash=events_hash
                )
                db.add(new_diary)
            
            await db.commit()
            is_refreshed = True
            diary_content = summary_content
        else:
            # 如果生成失敗且沒有現有內容，返回 None
            diary_content = existing_diary.content if existing_diary else None
    else:
        # 不需要刷新，返回現有內容
        diary_content = existing_diary.content if existing_diary else None
    
    return DiarySummaryResponse(
        diary_date=body.diary_date,
        content=diary_content,
        events_count=len(events),
        is_refreshed=is_refreshed
    )


@chat_router.get("/diary/{diary_date}", response_model=DiarySummaryResponse)
async def get_diary(
    request: Request,
    diary_date: date,
    db: AsyncSession = Depends(get_session),
):
    """
    獲取指定日期的日記（不刷新）
    """
    current_user = request.state.current_user
    
    stmt = select(diary_table.Table).where(
        and_(
            diary_table.Table.user_id == current_user.id,
            diary_table.Table.diary_date == diary_date
        )
    )
    result = await db.execute(stmt)
    diary = result.scalar_one_or_none()
    
    # 獲取事件數量
    date_str = diary_date.isoformat()
    user_timezone = user_service.get_user_timezone(current_user)
    events = await search_events_by_time(
        db=db,
        user_id=current_user.id,
        date_from=date_str,
        date_to=date_str,
        limit=100,
        user_timezone=user_timezone
    )
    
    return DiarySummaryResponse(
        diary_date=diary_date,
        content=diary.content if diary else None,
        events_count=len(events),
        is_refreshed=False
    )

