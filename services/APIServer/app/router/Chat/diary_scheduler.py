# -*- coding: utf-8 -*-
"""
日記自動刷新定時任務
"""
from __future__ import annotations
import asyncio
from datetime import date, datetime, timezone, timedelta
from typing import Optional
import pytz

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from ...DataAccess.Connect import AsyncSessionLocal
from ...DataAccess.tables import users, diary as diary_table
from ...router.User.settings import UserSettings
from .service import _calculate_events_hash, _generate_diary_summary
from .llm_tools import search_events_by_time


async def refresh_today_diary_for_user(user_id: int, db: AsyncSession) -> bool:
    """
    為指定使用者刷新當天的日記
    
    Returns:
        bool: 是否成功刷新
    """
    try:
        # 獲取使用者
        user = await db.get(users.Table, user_id)
        if not user:
            return False
        
        # 獲取使用者設定
        try:
            if user.settings:
                settings = UserSettings.model_validate(user.settings)
            else:
                from ...router.User.settings import get_default_user_settings
                settings = get_default_user_settings()
        except Exception:
            from ...router.User.settings import get_default_user_settings
            settings = get_default_user_settings()
        
        # 檢查是否啟用自動刷新
        if not settings.diary_auto_refresh_enabled:
            return False
        
        # 獲取使用者時區
        user_timezone = settings.timezone
        user_tz = pytz.timezone(user_timezone)
        
        # 獲取使用者時區的今天日期
        today_utc = datetime.now(timezone.utc)
        today_user = today_utc.astimezone(user_tz)
        today_date = today_user.date()
        
        # 獲取今天的事件
        date_str = today_date.isoformat()
        events = await search_events_by_time(
            db=db,
            user_id=user_id,
            date_from=date_str,
            date_to=date_str,
            limit=100,
            user_timezone=user_timezone
        )
        
        # 計算事件哈希值
        events_hash = _calculate_events_hash(events)
        
        # 查詢現有日記
        stmt = select(diary_table.Table).where(
            diary_table.Table.user_id == user_id,
            diary_table.Table.diary_date == today_date
        )
        result = await db.execute(stmt)
        existing_diary = result.scalar_one_or_none()
        
        # 檢查是否需要刷新
        if existing_diary and existing_diary.events_hash == events_hash:
            # 哈希值相同，不需要刷新
            return False
        
        # 需要刷新
        if len(events) == 0:
            summary_content = "今天沒有記錄到任何事件。"
        else:
            try:
                summary_content = await _generate_diary_summary(
                    events=events,
                    user_id=user_id,
                    user_timezone=user_timezone,
                    db=db
                )
            except HTTPException as http_err:
                # 如果是配額限制等 HTTP 錯誤，記錄但不更新日記
                if http_err.status_code == 429:
                    print(f"[Diary Scheduler] 使用者 {user_id} 的日記刷新因配額限制跳過")
                    return False
                # 其他 HTTP 錯誤也跳過
                print(f"[Diary Scheduler] 使用者 {user_id} 的日記刷新因 HTTP 錯誤跳過: {http_err.detail}")
                return False
            except Exception as e:
                # 其他錯誤，記錄但不更新日記
                print(f"[Diary Scheduler] 使用者 {user_id} 的日記刷新因錯誤跳過: {str(e)}")
                return False
        
        # 保存或更新日記
        if existing_diary:
            existing_diary.content = summary_content
            existing_diary.events_hash = events_hash
            db.add(existing_diary)
        else:
            new_diary = diary_table.Table(
                user_id=user_id,
                diary_date=today_date,
                content=summary_content,
                events_hash=events_hash
            )
            db.add(new_diary)
        
        await db.commit()
        print(f"[Diary Scheduler] 已刷新使用者 {user_id} 的當天日記")
        return True
    
    except Exception as e:
        print(f"[Diary Scheduler Error] 刷新使用者 {user_id} 的日記時發生錯誤: {str(e)}")
        await db.rollback()
        return False


async def refresh_all_users_today_diaries():
    """刷新所有使用者的當天日記"""
    async with AsyncSessionLocal() as db:
        try:
            # 獲取所有活躍使用者
            stmt = select(users.Table).where(users.Table.active == True)
            result = await db.execute(stmt)
            active_users = result.scalars().all()
            
            success_count = 0
            for user in active_users:
                try:
                    if await refresh_today_diary_for_user(user.id, db):
                        success_count += 1
                except Exception as e:
                    print(f"[Diary Scheduler Error] 處理使用者 {user.id} 時發生錯誤: {str(e)}")
                    continue
            
            print(f"[Diary Scheduler] 完成刷新，成功: {success_count}/{len(active_users)}")
        
        except Exception as e:
            print(f"[Diary Scheduler Error] 刷新所有使用者日記時發生錯誤: {str(e)}")


async def diary_refresh_scheduler(stop_event: asyncio.Event):
    """
    日記自動刷新定時任務
    
    Args:
        stop_event: 停止事件，當設置時任務會停止
    """
    print("[Diary Scheduler] 日記自動刷新任務已啟動")
    
    while not stop_event.is_set():
        try:
            # 獲取所有使用者的最小刷新間隔
            async with AsyncSessionLocal() as db:
                stmt = select(users.Table).where(users.Table.active == True)
                result = await db.execute(stmt)
                active_users = result.scalars().all()
                
                min_interval = 30  # 預設 30 分鐘
                for user in active_users:
                    try:
                        if user.settings:
                            settings = UserSettings.model_validate(user.settings)
                            if settings.diary_auto_refresh_enabled:
                                interval = settings.diary_auto_refresh_interval_minutes
                                if interval < min_interval:
                                    min_interval = interval
                    except Exception:
                        continue
                
                # 使用最小間隔作為等待時間
                wait_seconds = min_interval * 60
                print(f"[Diary Scheduler] 等待 {min_interval} 分鐘後刷新...")
            
            # 等待指定時間或直到停止事件被設置
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=wait_seconds)
                # 如果停止事件被設置，退出循環
                if stop_event.is_set():
                    break
            except asyncio.TimeoutError:
                # 超時，執行刷新
                pass
            
            # 執行刷新
            await refresh_all_users_today_diaries()
        
        except Exception as e:
            print(f"[Diary Scheduler Error] 定時任務發生錯誤: {str(e)}")
            # 發生錯誤時等待 5 分鐘後重試
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=300)
                if stop_event.is_set():
                    break
            except asyncio.TimeoutError:
                pass
    
    print("[Diary Scheduler] 日記自動刷新任務已停止")

