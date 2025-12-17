import os
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession
from ...DataAccess.Connect import get_session
from ...DataAccess.tables import events, diary, vlogs, music as music_table
from sqlalchemy import select, and_, func, desc
from ...security.deps import get_current_user, get_current_api_client, get_compute_api_client
from ...DataAccess.task_producer import enqueue
from .DTO import (
    VlogAISelectRequest, VlogAISelectResponse,
    DateEventsResponse, EventInfo,
    VlogCreateRequest, VlogCreateResponse,
    VlogListResponse, VlogInfo,
    VlogDetailResponse, VlogSegmentInfo,
    VlogUrlResponse, DailyVlogResponse,
    VlogInternalSegmentRequest, VlogInternalSegmentInfoResponse,
    VlogStatusUpdate, VlogStatusUpdateResponse
)
from datetime import datetime, date, time, timezone, timedelta
import uuid
from typing import List, Dict, Any
import pytz
import asyncio
from urllib.parse import quote
from ...utils import generate_presigned_url, normalize_s3_key

vlogs_router = APIRouter(prefix="/vlogs", tags=["vlogs"])
VLOGS_BUCKET = os.getenv("MINIO_BUCKET", "media-bucket")

async def _remove_previous_daily_vlogs(db: AsyncSession, current_vlog: vlogs.Table):
    """刪除同一天既有的舊 Vlog 檔案，只保留最新的紀錄。"""
    print(f"[Vlog API] _remove_previous_daily_vlogs: 當前 vlog_id={current_vlog.id}, target_date={current_vlog.target_date}, user_id={current_vlog.user_id}")
    
    stmt = select(vlogs.Table).where(
        and_(
            vlogs.Table.user_id == current_vlog.user_id,
            vlogs.Table.target_date == current_vlog.target_date,
            vlogs.Table.id != current_vlog.id
        )
    )
    result = await db.execute(stmt)
    others = result.scalars().all()

    if not others:
        print(f"[Vlog API] _remove_previous_daily_vlogs: 沒有找到需要刪除的舊 vlog")
        return

    print(f"[Vlog API] _remove_previous_daily_vlogs: 找到 {len(others)} 個舊 vlog 需要刪除")
    for other in others:
        print(f"[Vlog API]   將刪除: id={other.id}, target_date={other.target_date}, status={other.status}, created_at={other.created_at}")

    from ...config.minio_client import get_minio_client
    client = get_minio_client()

    for other in others:
        if other.s3_key:
            try:
                client.remove_object(VLOGS_BUCKET, other.s3_key)
                print(f"[Vlog API]   已刪除 S3 文件: {other.s3_key}")
            except Exception as e:
                print(f"[Vlog] 刪除舊影片失敗 ({other.s3_key}): {e}")
        await db.delete(other)
    
    print(f"[Vlog API] _remove_previous_daily_vlogs: 完成，已刪除 {len(others)} 個舊 vlog")


async def _perform_rag_selection(query: str, candidates: List[Dict[str, Any]], top_k: int = 20) -> List[str]:
    """本地執行 RAG 選擇邏輯（當 Celery 結果後端未配置時使用）。
    
    使用 BM25 演算法進行文字檢索，找出與查詢最相關的候選項目。
    
    Args:
        query: 查詢字串
        candidates: 候選項目列表，每個項目包含 id 和 text
        top_k: 返回前 k 個最相關的結果
        
    Returns:
        List[str]: 最相關的候選項目 ID 列表
    """
    if not candidates:
        return []
    
    # 在執行器中運行 CPU 密集型操作
    def _rag_logic():
        import numpy as np
        try:
            # 導入 jieba 和 BM25
            import jieba
            from rank_bm25 import BM25Okapi
            
            # 準備數據
            chunks = [c['text'] for c in candidates if c.get('text')]
            ids = [c['id'] for c in candidates]
            
            if not chunks:
                return []
            
            # BM25 檢索
            tokenized_chunks = [list(jieba.cut(chunk)) for chunk in chunks]
            bm25 = BM25Okapi(tokenized_chunks)
            tokenized_query = list(jieba.cut(query))
            bm25_scores = bm25.get_scores(tokenized_query)
            bm25_ranked_indices = np.argsort(bm25_scores)[::-1]
            bm25_ranked_ids = [ids[i] for i in bm25_ranked_indices]
            
            # 向量相似度檢索（如果有 embedding）
            has_embeddings = any(c.get('embedding') for c in candidates)
            
            if has_embeddings:
                # 這裡需要使用 embedding 模型,但由於是同步函數,我們先用 BM25 結果
                # 如果需要向量搜索,應該異步調用 Compute Server
                # 暫時只用 BM25
                return bm25_ranked_ids[:top_k]
            else:
                # 只有 BM25
                return bm25_ranked_ids[:top_k]
        
        except Exception as e:
            print(f"RAG 邏輯執行失敗: {e}")
            # 返回前幾個作為備選
            return [c['id'] for c in candidates[:top_k]]
    
    # 在線程池中執行
    loop = asyncio.get_running_loop()
    selected_ids = await loop.run_in_executor(None, _rag_logic)
    return selected_ids

@vlogs_router.get("/events/{target_date}", response_model=DateEventsResponse)
async def get_date_events(
    target_date: date = Path(..., description="目標日期 (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_session),
    current_user = Depends(get_current_user)
):
    """獲取指定日期的所有事件(用於手動選擇)"""
    
    # 獲取使用者時區設定
    from ...router.User.service import UserService
    user_service = UserService()
    user_timezone = user_service.get_user_timezone(current_user)
    
    # 構建日期範圍 (使用使用者時區)
    user_tz = pytz.timezone(user_timezone)
    day_start = user_tz.localize(datetime.combine(target_date, time.min))
    day_end = user_tz.localize(datetime.combine(target_date, time.max))
    
    # 轉換為 UTC
    day_start_utc = day_start.astimezone(timezone.utc)
    day_end_utc = day_end.astimezone(timezone.utc)
    
    # 查詢該日期的事件
    stmt = select(events.Table).where(
        and_(
            events.Table.user_id == current_user.id,
            events.Table.start_time >= day_start_utc,
            events.Table.start_time <= day_end_utc
        )
    ).order_by(events.Table.start_time.asc())
    
    result = await db.execute(stmt)
    events_list = result.scalars().all()
    
    # 轉換為響應格式
    event_infos = []
    for e in events_list:
        event_infos.append(EventInfo(
            id=str(e.id),
            action=e.action,
            scene=e.scene,
            summary=e.summary,
            start_time=e.start_time,
            duration=e.duration,
            recording_id=str(e.recording_id) if e.recording_id else None
        ))
    
    return DateEventsResponse(
        date=target_date,
        events=event_infos
    )

@vlogs_router.post("/ai-select", response_model=VlogAISelectResponse)
async def ai_select_vlog_clips(
    body: VlogAISelectRequest,
    db: AsyncSession = Depends(get_session),
    current_user = Depends(get_current_user)
):
    """使用 AI (RAG) 自動選擇適合的事件片段"""
    
    target_date = body.date
    
    # 構建日期範圍（使用使用者時區）
    from ...router.User.service import UserService
    user_service = UserService()
    user_timezone = user_service.get_user_timezone(current_user)
    user_tz = pytz.timezone(user_timezone)
    day_start = user_tz.localize(datetime.combine(target_date, time.min))
    day_end = user_tz.localize(datetime.combine(target_date, time.max))
    day_start_utc = day_start.astimezone(timezone.utc)
    day_end_utc = day_end.astimezone(timezone.utc)
    
    # 查詢該日期的事件
    stmt = select(events.Table).where(
        and_(
            events.Table.user_id == current_user.id,
            events.Table.start_time >= day_start_utc,
            events.Table.start_time <= day_end_utc
        )
    )
    
    res = await db.execute(stmt)
    events_list = res.scalars().all()
    
    if not events_list:
        return VlogAISelectResponse(selected_event_ids=[])

    # 獲取查詢文本 (日記或自定義)
    query = body.summary_text
    if not query:
        # 嘗試從日記獲取
        stmt_diary = select(diary.Table).where(
            and_(
                diary.Table.user_id == current_user.id,
                diary.Table.diary_date == target_date
            )
        )
        res_diary = await db.execute(stmt_diary)
        d = res_diary.scalar_one_or_none()
        if d:
            query = d.content
    
    if not query:
        # 沒有日記,使用通用查詢
        query = "今天發生的有趣、開心、有意義的事情"

    # 準備候選事件
    candidates = []
    for e in events_list:
        emb = None
        if e.embedding is not None:
            try:
                emb = e.embedding.tolist() if hasattr(e.embedding, 'tolist') else list(e.embedding)
            except:
                emb = None
                
        candidates.append({
            "id": str(e.id),
            "text": e.summary or "",
            "embedding": emb
        })
    
    # 直接使用同步方式調用 RAG (不使用 Celery,因為需要立即結果)
    try:
        # 調用 Celery 任務但不等待結果,改為直接執行邏輯
        from ...DataAccess.task_producer import enqueue
        from ...DataAccess.tables import inference_jobs
        from ...DataAccess.tables.__Enumeration import JobStatus
        
        # 任務管理追蹤：建立 inference_jobs（rag_highlights）
        rag_job = inference_jobs.Table(
            type="rag_highlights",
            status=JobStatus.pending,
            input_type="rag",
            input_url=str(target_date),
            output_url=None,
            trace_id=f"rag-{current_user.id}-{target_date.isoformat()}",
            params={
                "user_id": int(current_user.id),
                "limit": int(body.limit),
                "candidates_count": int(len(candidates)),
                "progress": 0.0,
            },
            metrics=None,
        )
        db.add(rag_job)
        await db.commit()
        await db.refresh(rag_job)

        # 方案 1: 使用 Celery 同步取結果
        task_result = enqueue("tasks.suggest_vlog_highlights", {
            "query": query,
            "candidates": candidates,
            "limit": body.limit,
            "job_id": str(rag_job.id),
            "user_id": int(current_user.id),
        })
        
        # 嘗試獲取結果 (如果配置了結果後端)
        import asyncio
        from functools import partial
        
        def wait_for_task(task_res):
            try:
                return task_res.get(timeout=120)  # 等待時間改為 2 分鐘
            except Exception as e:
                print(f"獲取任務結果失敗: {e}")
                return None
        
        loop = asyncio.get_running_loop()
        selected_ids = await loop.run_in_executor(None, partial(wait_for_task, task_result))
        
        if selected_ids is None:
            # 如果 Celery 結果後端未配置,直接在這裡執行邏輯
            print("[Vlog AI Select] Celery 結果後端未配置,使用本地 RAG 計算")
            selected_ids = await _perform_rag_selection(query, candidates, top_k=body.limit)
        
    except Exception as e:
        print(f"RAG 任務失敗: {e}")
        # 失敗時嘗試本地計算
        try:
            selected_ids = await _perform_rag_selection(query, candidates, top_k=body.limit)
        except Exception as e2:
            print(f"本地 RAG 計算也失敗: {e2}")
            return VlogAISelectResponse(selected_event_ids=[])
        
    return VlogAISelectResponse(selected_event_ids=selected_ids if selected_ids else [])

@vlogs_router.post("", response_model=VlogCreateResponse, status_code=201)
async def create_vlog(
    body: VlogCreateRequest,
    db: AsyncSession = Depends(get_session),
    current_user = Depends(get_current_user)
):
    """創建 Vlog (發送到 Compute Server 進行剪輯)"""
    
    # 驗證事件 ID 是否屬於該用戶
    event_uuids = [uuid.UUID(eid) for eid in body.event_ids]
    
    stmt = select(events.Table).where(
        and_(
            events.Table.id.in_(event_uuids),
            events.Table.user_id == current_user.id
        )
    )
    result = await db.execute(stmt)
    valid_events = result.scalars().all()
    
    if len(valid_events) != len(body.event_ids):
        raise HTTPException(status_code=400, detail="部分事件 ID 無效或不屬於該用戶")
    
    # 檢查事件是否都在同一天（驗證用，但不覆蓋 body.target_date）
    # 獲取使用者時區設定
    from ...router.User.service import UserService
    user_service = UserService()
    user_timezone = user_service.get_user_timezone(current_user)
    
    dates = set()
    for e in valid_events:
        if e.start_time:
            user_tz = pytz.timezone(user_timezone)
            # 確保 start_time 有時區資訊
            if e.start_time.tzinfo is None:
                e_start_time = e.start_time.replace(tzinfo=timezone.utc)
            else:
                e_start_time = e.start_time
            local_time = e_start_time.astimezone(user_tz)
            dates.add(local_time.date())
    
    if len(dates) > 1:
        raise HTTPException(status_code=400, detail="事件必須在同一天內")
    
    # 驗證 body.target_date 與事件日期是否一致（可選，用於調試）
    if dates and body.target_date not in dates:
        print(f"[Vlog API] 警告: body.target_date={body.target_date} 與事件日期 {dates} 不一致，但繼續使用 body.target_date")
    
    # 創建 Vlog 記錄（使用 body.target_date，不從事件推導）
    music_settings = None
    if body.music_id:
        print(f"[Vlog API] 收到音樂請求: music_id={body.music_id}, start={body.music_start}, end={body.music_end}, fade={body.music_fade}, volume={body.music_volume}")
        try:
            music_uuid = uuid.UUID(body.music_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="無效的音樂 ID")

        stmt_music = select(music_table.Table).where(music_table.Table.id == music_uuid)
        music_result = await db.execute(stmt_music)
        music_record = music_result.scalar_one_or_none()
        if not music_record:
            raise HTTPException(status_code=404, detail="音樂不存在")

        start_time = float(body.music_start or 0.0)
        if start_time < 0:
            start_time = 0.0
        if body.music_end is not None:
            end_time = float(body.music_end)
        else:
            end_time = float(music_record.duration or 0.0)

        if end_time <= start_time:
            raise HTTPException(status_code=400, detail="音樂結束時間需大於開始時間")

        music_settings = {
            "music_id": str(music_record.id),
            "s3_key": music_record.s3_key,
            "content_type": music_record.content_type,
            "name": music_record.name,
            "composer": music_record.composer,
            "duration": music_record.duration,
            "start": start_time,
            "end": end_time,
            "fade": bool(body.music_fade),
        }
        if body.music_volume is not None:
            music_settings["volume"] = max(0.0, min(1.0, float(body.music_volume)))
        
        print(f"[Vlog API] 音樂設定已準備: {music_settings}")

    new_vlog = vlogs.Table(
        user_id=current_user.id,
        title=body.title or f"{body.target_date} 的 Vlog",
        target_date=body.target_date,
        status='pending',
        progress=0.0,
        status_message="等待排程開始",
        settings={
            "max_duration": body.max_duration,
            "resolution": body.resolution,
            "music": music_settings
        }
    )
    
    print(f"[Vlog API] 創建 vlog: user_id={current_user.id}, target_date={body.target_date} (type: {type(body.target_date)})")
    
    db.add(new_vlog)
    await db.flush()
    await db.refresh(new_vlog)
    
    print(f"[Vlog API] vlog 已創建: id={new_vlog.id}, target_date={new_vlog.target_date} (type: {type(new_vlog.target_date)}), status={new_vlog.status}")
    
    # 創建 Vlog 片段記錄
    for idx, event in enumerate(sorted(valid_events, key=lambda e: e.start_time or datetime.min)):
        segment = vlogs.SegmentTable(
            vlog_id=new_vlog.id,
            recording_id=event.recording_id,
            event_id=event.id,
            start_offset=0.0,  # 將由 Compute Server 決定
            end_offset=event.duration or 0.0,
            sequence_order=idx
        )
        db.add(segment)
    
    await db.commit()
    
    # ✅ 任務管理追蹤：建立 inference_jobs（vlog_generation），並把 job_id 存回 vlog.settings
    # 這樣 /admin/tasks 就能從 inference_jobs 顯示 vlog 任務狀態。
    try:
        from ...DataAccess.tables import inference_jobs
        from ...DataAccess.tables.__Enumeration import JobStatus

        job = inference_jobs.Table(
            type="vlog_generation",
            status=JobStatus.pending,
            input_type="vlog",
            input_url=None,
            output_url=None,
            trace_id=str(new_vlog.id),
            params={
                "user_id": int(current_user.id),
                "vlog_id": str(new_vlog.id),
                "event_ids": list(body.event_ids or []),
                "progress": 0.0,
            },
            metrics=None,
        )
        db.add(job)
        await db.flush()
        await db.refresh(job)

        # 將 job_id 存到 settings（避免新增欄位，向後相容）
        settings_dict = new_vlog.settings if isinstance(new_vlog.settings, dict) else {}
        settings_dict = {**settings_dict, "job_id": str(job.id)}
        new_vlog.settings = settings_dict
        db.add(new_vlog)
        await db.commit()
        await db.refresh(new_vlog)
    except Exception as e:
        # 不影響主流程：即使任務追蹤寫入失敗，仍允許啟動 vlog 任務
        print(f"[Vlog API] 建立 inference_jobs 追蹤失敗: {e}")

    # 發送到 Compute Server 進行處理
    try:
        task_settings = {
            "max_duration": body.max_duration,
            "resolution": body.resolution,
            "music": music_settings
        }
        print(f"[Vlog API] 發送任務到 Compute Server: vlog_id={new_vlog.id}, settings={task_settings}")
        enqueue("tasks.generate_vlog", kwargs={
            "vlog_id": str(new_vlog.id),
            "user_id": current_user.id,
            "event_ids": body.event_ids,
            "settings": task_settings
        })
    except Exception as e:
        print(f"發送 Vlog 生成任務失敗: {e}")
        # 更新狀態為失敗
        new_vlog.status = 'failed'
        await db.commit()
        raise HTTPException(status_code=500, detail="無法啟動 Vlog 生成任務")
    
    return VlogCreateResponse(
        vlog_id=str(new_vlog.id),
        status='pending',
        message="Vlog 生成任務已啟動"
    )

@vlogs_router.get("", response_model=VlogListResponse)
async def list_vlogs(
    skip: int = Query(0, ge=0, description="跳過記錄數"),
    limit: int = Query(20, ge=1, le=100, description="返回記錄數"),
    status: str | None = Query(None, description="按狀態過濾"),
    db: AsyncSession = Depends(get_session),
    current_user = Depends(get_current_user)
):
    """獲取用戶的 Vlog 列表"""
    
    # 構建查詢
    stmt = select(vlogs.Table).where(vlogs.Table.user_id == current_user.id)
    
    if status:
        stmt = stmt.where(vlogs.Table.status == status)
    
    # 計算總數
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar()
    
    # 獲取分頁數據
    stmt = stmt.order_by(desc(vlogs.Table.created_at)).offset(skip).limit(limit)
    result = await db.execute(stmt)
    vlog_list = result.scalars().all()
    
    # 轉換為響應格式
    vlog_infos = []
    for v in vlog_list:
        vlog_infos.append(VlogInfo(
            id=str(v.id),
            title=v.title,
            target_date=v.target_date,
            status=v.status,
            duration=v.duration,
            s3_key=v.s3_key,
            thumbnail_s3_key=v.thumbnail_s3_key,
            created_at=v.created_at,
            updated_at=v.updated_at,
            progress=v.progress,
            status_message=v.status_message
        ))
    
    return VlogListResponse(
        items=vlog_infos,
        total=total or 0
    )

@vlogs_router.get("/date/{target_date}", response_model=DailyVlogResponse)
async def get_vlog_by_date(
    target_date: date = Path(..., description="Vlog 日期 (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_session),
    current_user = Depends(get_current_user)
):
    """獲取指定日期的最新 Vlog"""
    print(f"[Vlog API] get_vlog_by_date: user_id={current_user.id}, target_date={target_date} (type: {type(target_date)})")
    
    # 先查詢該用戶的所有 vlog（用於調試）
    debug_stmt = select(vlogs.Table).where(vlogs.Table.user_id == current_user.id).order_by(vlogs.Table.created_at.desc()).limit(20)
    debug_result = await db.execute(debug_stmt)
    debug_vlogs = debug_result.scalars().all()
    print(f"[Vlog API] 該用戶現有的 vlog 數量: {len(debug_vlogs)}")
    for dv in debug_vlogs:
        print(f"[Vlog API]   現有 vlog: id={dv.id}, target_date={dv.target_date} (type: {type(dv.target_date)}), status={dv.status}, created_at={dv.created_at}")
    
    stmt = (
        select(vlogs.Table)
        .where(
            and_(
                vlogs.Table.user_id == current_user.id,
                vlogs.Table.target_date == target_date
            )
        )
        .order_by(vlogs.Table.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    vlog = result.scalar_one_or_none()

    if not vlog:
        print(f"[Vlog API] 未找到 vlog，查詢參數: user_id={current_user.id}, target_date={target_date} (type: {type(target_date)})")
        # 嘗試查找是否有 status=completed 的 vlog（即使日期不匹配）
        completed_stmt = select(vlogs.Table).where(
            and_(
                vlogs.Table.user_id == current_user.id,
                vlogs.Table.status == 'completed'
            )
        ).order_by(vlogs.Table.created_at.desc()).limit(5)
        completed_result = await db.execute(completed_stmt)
        completed_vlogs = completed_result.scalars().all()
        print(f"[Vlog API] 該用戶已完成的 vlog 數量: {len(completed_vlogs)}")
        for cv in completed_vlogs:
            print(f"[Vlog API]   已完成 vlog: id={cv.id}, target_date={cv.target_date}, status={cv.status}")
        raise HTTPException(status_code=404, detail="該日期尚未生成 Vlog")

    # 狀態同步：如果 vlog 處於 processing，但對應的 inference_jobs 已失敗，則同步更新
    resolved_error_message = None
    if vlog.status == 'processing':
        from ...DataAccess.tables import inference_jobs
        from ...DataAccess.tables.__Enumeration import JobStatus
        
        job_id = vlog.settings.get('job_id') if vlog.settings else None
        if job_id:
            job_stmt = select(inference_jobs.Table).where(inference_jobs.Table.id == job_id)
            job_result = await db.execute(job_stmt)
            job = job_result.scalar_one_or_none()
            
            if job and job.status == JobStatus.failed:
                # inference_jobs 已失敗，同步更新 vlog 狀態
                print(f"[Vlog API] 偵測到狀態不一致：vlog {vlog.id} 是 processing，但 job {job_id} 已失敗，同步更新")
                vlog.status = 'failed'
                resolved_error_message = job.error_message or "任務執行失敗"
                vlog.status_message = resolved_error_message
                # vlogs 表沒有 error_message 欄位：寫入 settings 以便前端取得
                try:
                    s = vlog.settings if isinstance(vlog.settings, dict) else {}
                    s = {**s, "error_message": resolved_error_message, "job_id": str(job_id)}
                    vlog.settings = s
                except Exception:
                    pass
                await db.commit()
                await db.refresh(vlog)

    # 若未在同步流程取得，從 settings/status_message 取回錯誤資訊（避免 ORM 欄位不存在）
    if resolved_error_message is None:
        if isinstance(vlog.settings, dict):
            resolved_error_message = vlog.settings.get("error_message")
        if not resolved_error_message and vlog.status == "failed":
            resolved_error_message = vlog.status_message

    return DailyVlogResponse(
        id=str(vlog.id),
        title=vlog.title,
        target_date=vlog.target_date,
        status=vlog.status,
        duration=vlog.duration,
        s3_key=vlog.s3_key,
        thumbnail_s3_key=vlog.thumbnail_s3_key,
        progress=vlog.progress,
        status_message=vlog.status_message,
        error_message=resolved_error_message,
        settings=vlog.settings,
        created_at=vlog.created_at,
        updated_at=vlog.updated_at
    )

@vlogs_router.get("/{vlog_id}", response_model=VlogDetailResponse)
async def get_vlog_detail(
    vlog_id: uuid.UUID = Path(..., description="Vlog ID"),
    db: AsyncSession = Depends(get_session),
    current_user = Depends(get_current_user)
):
    """獲取 Vlog 詳細信息"""
    
    # 查詢 Vlog
    stmt = select(vlogs.Table).where(
        and_(
            vlogs.Table.id == vlog_id,
            vlogs.Table.user_id == current_user.id
        )
    )
    result = await db.execute(stmt)
    vlog = result.scalar_one_or_none()
    
    if not vlog:
        raise HTTPException(status_code=404, detail="Vlog 不存在")
    
    # 查詢片段
    stmt_segments = select(vlogs.SegmentTable).where(
        vlogs.SegmentTable.vlog_id == vlog_id
    ).order_by(vlogs.SegmentTable.sequence_order.asc())
    
    result_segments = await db.execute(stmt_segments)
    segments = result_segments.scalars().all()
    
    # 轉換為響應格式
    segment_infos = []
    for s in segments:
        segment_infos.append(VlogSegmentInfo(
            recording_id=str(s.recording_id),
            event_id=str(s.event_id) if s.event_id else None,
            start_offset=s.start_offset,
            end_offset=s.end_offset,
            sequence_order=s.sequence_order
        ))
    
    return VlogDetailResponse(
        id=str(vlog.id),
        title=vlog.title,
        target_date=vlog.target_date,
        status=vlog.status,
        duration=vlog.duration,
        s3_key=vlog.s3_key,
        thumbnail_s3_key=vlog.thumbnail_s3_key,
        settings=vlog.settings,
        segments=segment_infos,
        created_at=vlog.created_at,
        updated_at=vlog.updated_at,
        progress=vlog.progress,
        status_message=vlog.status_message
    )

@vlogs_router.get("/{vlog_id}/url", response_model=VlogUrlResponse)
async def get_vlog_url(
    vlog_id: uuid.UUID = Path(..., description="Vlog ID"),
    ttl: int = Query(3600, ge=60, le=86400, description="URL 有效時間(秒)"),
    db: AsyncSession = Depends(get_session),
    current_user = Depends(get_current_user),
    request: Request = None
):
    """獲取 Vlog 播放 URL (預簽名 S3 URL)"""
    
    # 查詢 Vlog
    stmt = select(vlogs.Table).where(
        and_(
            vlogs.Table.id == vlog_id,
            vlogs.Table.user_id == current_user.id
        )
    )
    result = await db.execute(stmt)
    vlog = result.scalar_one_or_none()
    
    if not vlog:
        raise HTTPException(status_code=404, detail="Vlog 不存在")
    
    if vlog.status != 'completed':
        raise HTTPException(status_code=400, detail=f"Vlog 狀態為 {vlog.status},無法播放")
    
    if not vlog.s3_key:
        raise HTTPException(status_code=404, detail="Vlog 文件不存在")
    
    try:
        normalized_key = normalize_s3_key(vlog.s3_key)
        filename = normalized_key.rsplit("/", 1)[-1]
        disposition = f'inline; filename="{quote(filename)}"'
        url = generate_presigned_url(
            normalized_key,
            ttl,
            content_type="video/mp4",
            content_disposition=disposition,
            request=request
        )
        expires_at = int(datetime.now(timezone.utc).timestamp()) + ttl

        return VlogUrlResponse(
            url=url,
            ttl=ttl,
            expires_at=expires_at
        )
    except Exception as e:
        print(f"生成 Vlog URL 失敗: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="無法生成播放 URL")

@vlogs_router.get("/{vlog_id}/thumbnail-url", response_model=VlogUrlResponse)
async def get_vlog_thumbnail_url(
    vlog_id: uuid.UUID = Path(..., description="Vlog ID"),
    ttl: int = Query(3600, ge=60, le=86400, description="URL 有效時間(秒)"),
    db: AsyncSession = Depends(get_session),
    current_user = Depends(get_current_user),
    request: Request = None
):
    """獲取 Vlog 縮圖 URL (預簽名 S3 URL)"""
    
    # 查詢 Vlog
    stmt = select(vlogs.Table).where(
        and_(
            vlogs.Table.id == vlog_id,
            vlogs.Table.user_id == current_user.id
        )
    )
    result = await db.execute(stmt)
    vlog = result.scalar_one_or_none()
    
    if not vlog:
        raise HTTPException(status_code=404, detail="Vlog 不存在")
    
    if not vlog.thumbnail_s3_key:
        raise HTTPException(status_code=404, detail="Vlog 縮圖不存在")
    
    try:
        normalized_key = normalize_s3_key(vlog.thumbnail_s3_key)
        filename = normalized_key.rsplit("/", 1)[-1]
        disposition = f'inline; filename="{quote(filename)}"'
        url = generate_presigned_url(
            normalized_key,
            ttl,
            content_type="image/jpeg",
            content_disposition=disposition,
            request=request
        )
        expires_at = int(datetime.now(timezone.utc).timestamp()) + ttl

        return VlogUrlResponse(
            url=url,
            ttl=ttl,
            expires_at=expires_at
        )
    except Exception as e:
        print(f"生成 Vlog 縮圖 URL 失敗: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="無法生成縮圖 URL")

@vlogs_router.delete("/{vlog_id}")
async def delete_vlog(
    vlog_id: uuid.UUID = Path(..., description="Vlog ID"),
    db: AsyncSession = Depends(get_session),
    current_user = Depends(get_current_user)
):
    """刪除 Vlog"""
    
    # 查詢 Vlog
    stmt = select(vlogs.Table).where(
        and_(
            vlogs.Table.id == vlog_id,
            vlogs.Table.user_id == current_user.id
        )
    )
    result = await db.execute(stmt)
    vlog = result.scalar_one_or_none()
    
    if not vlog:
        raise HTTPException(status_code=404, detail="Vlog 不存在")
    
    # 刪除 S3 文件
    if vlog.s3_key:
        from ...config.minio_client import get_minio_client
        try:
            client = get_minio_client()
            client.remove_object(
                bucket_name=VLOGS_BUCKET,
                object_name=vlog.s3_key
            )
        except Exception as e:
            print(f"刪除 S3 文件失敗: {e}")
    
    # 刪除數據庫記錄 (CASCADE 會自動刪除 segments)
    await db.delete(vlog)
    await db.commit()
    
    return {"ok": True, "message": "Vlog 已刪除"}

# ==========================================
# 內部 API (供 Compute Server 使用)
# ==========================================

@vlogs_router.post("/internal/segments", response_model=List[VlogInternalSegmentInfoResponse])
async def internal_get_vlog_segments(
    body: VlogInternalSegmentRequest,
    db: AsyncSession = Depends(get_session),
    api_client = Depends(get_compute_api_client)
):
    """
    [內部] 獲取事件對應的視頻片段信息
    供 Compute Server 調用以獲取剪輯所需的 S3 Key 和時間偏移
    """
    if not body.event_ids:
        return []
        
    # 轉換 UUID
    try:
        event_uuids = [uuid.UUID(eid) for eid in body.event_ids]
    except ValueError:
        raise HTTPException(status_code=400, detail="無效的事件 ID 格式")
    
    # 查詢事件和對應的錄影信息
    # 注意: 這裡需要 join recordings 表
    from ...DataAccess.tables import recordings
    
    stmt = select(
        events.Table.id.label("event_id"),
        events.Table.recording_id,
        events.Table.start_time,
        events.Table.duration.label("event_duration"),
        recordings.Table.s3_key,
        recordings.Table.start_time.label("recording_start_time"),
        recordings.Table.duration.label("recording_duration")
    ).join(
        recordings.Table, events.Table.recording_id == recordings.Table.id
    ).where(
        events.Table.id.in_(event_uuids)
    )
    
    result = await db.execute(stmt)
    rows = result.all()
    
    segments = []
    for row in rows:
        # 計算偏移量
        offset = 0.0
        if row.start_time and row.recording_start_time:
            # 確保是 datetime 對象
            st = row.start_time
            rst = row.recording_start_time
            # 如果是 naive datetime, 假設是 UTC (資料庫中存儲的通常是 naive UTC)
            if st.tzinfo is None: st = st.replace(tzinfo=timezone.utc)
            if rst.tzinfo is None: rst = rst.replace(tzinfo=timezone.utc)
            
            offset = (st - rst).total_seconds()
        
        segments.append(VlogInternalSegmentInfoResponse(
            event_id=str(row.event_id),
            recording_id=str(row.recording_id),
            s3_key=row.s3_key,
            start_offset=max(0.0, offset),
            duration=float(row.event_duration or 10.0),
            recording_duration=float(row.recording_duration or 0.0)
        ))
    
    return segments

@vlogs_router.patch("/internal/{vlog_id}/status", response_model=VlogStatusUpdateResponse)
async def internal_update_vlog_status(
    vlog_id: uuid.UUID,
    body: VlogStatusUpdate,
    db: AsyncSession = Depends(get_session),
    api_client = Depends(get_compute_api_client)
):
    """
    [內部] 更新 Vlog 狀態
    供 Compute Server 報告任務進度和結果
    """
    stmt = select(vlogs.Table).where(vlogs.Table.id == vlog_id)
    result = await db.execute(stmt)
    vlog = result.scalar_one_or_none()
    
    if not vlog:
        raise HTTPException(status_code=404, detail="Vlog 不存在")
    
    # 記錄更新前的狀態（用於調試）
    print(f"[Vlog API] 更新 vlog 狀態: vlog_id={vlog_id}, 當前 target_date={vlog.target_date}, 當前 status={vlog.status}")
    print(f"[Vlog API] 更新內容: status={body.status}, s3_key={body.s3_key}, duration={body.duration}, thumbnail_s3_key={body.thumbnail_s3_key}")
    
    # 更新狀態
    if body.status:
        vlog.status = body.status
    vlog.updated_at = datetime.now(timezone.utc)
    
    if body.s3_key:
        vlog.s3_key = body.s3_key
    
    if body.thumbnail_s3_key:
        vlog.thumbnail_s3_key = body.thumbnail_s3_key
        print(f"[Vlog API] 已設置縮圖路徑: {body.thumbnail_s3_key}")
    elif body.thumbnail_s3_key is None and body.status == 'completed':
        # 如果狀態是完成但沒有縮圖，記錄警告
        print(f"[Vlog API] 警告: Vlog {vlog_id} 完成但沒有縮圖路徑")
    
    if body.duration is not None:
        vlog.duration = body.duration
    
    if body.progress is not None:
        vlog.progress = max(0.0, min(100.0, body.progress))
    
    if body.status_message is not None:
        vlog.status_message = body.status_message
        
    # 處理錯誤信息
    if body.error_message and (body.status == 'failed' or vlog.status == 'failed'):
        print(f"Vlog {vlog_id} 生成失敗: {body.error_message}")
        # 將 error_message 寫入 vlog.status_message (因為 vlogs 表沒有 error_message 欄位)
        if not vlog.status_message or "失敗" in body.error_message:
            vlog.status_message = body.error_message
        # 同時寫入 settings，供前端顯示更明確的錯誤原因
        try:
            s = vlog.settings if isinstance(vlog.settings, dict) else {}
            vlog.settings = {**s, "error_message": body.error_message}
        except Exception:
            pass
    
    # 如果同一天已有舊影片，完成後清除舊檔
    if vlog.status == 'completed' and vlog.s3_key:
        await _remove_previous_daily_vlogs(db, vlog)
    
    # ✅ 同步更新 inference_jobs（若此 vlog 有被追蹤）
    try:
        from ...DataAccess.tables import inference_jobs
        from ...DataAccess.tables.__Enumeration import JobStatus
        
        # 優先使用 body.job_id，否則從 vlog.settings 中獲取
        job_id = body.job_id
        if not job_id and isinstance(vlog.settings, dict):
            job_id = vlog.settings.get("job_id")
        
        if job_id:
            try:
                jid = uuid.UUID(str(job_id))
            except Exception:
                jid = None
            if jid:
                job_stmt = select(inference_jobs.Table).where(inference_jobs.Table.id == jid)
                job_res = await db.execute(job_stmt)
                job = job_res.scalar_one_or_none()
                if job:
                    # status 映射：vlog(pending/processing/completed/failed) -> inference_jobs(pending/processing/success/failed)
                    vlog_status = (body.status or vlog.status or "").lower()
                    mapped = {
                        "pending": JobStatus.pending,
                        "processing": JobStatus.processing,
                        "completed": JobStatus.success,
                        "failed": JobStatus.failed,
                    }.get(vlog_status, job.status)
                    job.status = mapped
                    if vlog.s3_key:
                        job.output_url = vlog.s3_key
                    # params: progress / status_message / vlog_id
                    params = job.params if isinstance(job.params, dict) else {}
                    if body.progress is not None:
                        params["progress"] = max(0.0, min(100.0, float(body.progress)))
                    if body.status_message is not None:
                        params["status_message"] = body.status_message
                    params["vlog_id"] = str(vlog.id)
                    params["user_id"] = int(vlog.user_id)
                    job.params = params
                    
                    # 同步 progress
                    if body.progress is not None:
                        job.progress = body.progress
                    elif vlog.progress is not None:
                        job.progress = vlog.progress
                    
                    # 同步 error_message
                    if body.error_message:
                        job.error_message = body.error_message
                    
                    # 同步 duration
                    if body.duration is not None:
                        job.duration = body.duration
                        metrics = job.metrics if isinstance(job.metrics, dict) else {}
                        metrics["duration"] = float(body.duration)
                        job.metrics = metrics
                    
                    job.updated_at = datetime.now(timezone.utc)
                    db.add(job)
                    print(f"[Vlog API] 同步更新 inference_jobs: job_id={jid}, status={mapped.value}, progress={job.progress}, error={job.error_message}")
    except Exception as e:
        print(f"[Vlog API] 更新 inference_jobs 追蹤失敗: {e}")

    await db.commit()
    await db.refresh(vlog)
    
    # 記錄更新後的狀態（用於調試）
    print(f"[Vlog API] 更新完成: vlog_id={vlog_id}, target_date={vlog.target_date}, status={vlog.status}, s3_key={vlog.s3_key}")
    
    return VlogStatusUpdateResponse(
        vlog_id=str(vlog.id),
        status=vlog.status,
        progress=vlog.progress,
        status_message=vlog.status_message,
        s3_key=vlog.s3_key,
        duration=vlog.duration
    )
