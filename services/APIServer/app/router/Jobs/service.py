# -*- coding: utf-8 -*-
"""
唯一不需要注入API Key 或 User ID 的 router ， 針對不同 Path 注入不同的依賴
"""
from __future__ import annotations
from typing import Optional
import uuid
import os
from datetime import datetime, timedelta
import uuid_utils as uuidu
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import update, select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ...DataAccess.Connect import get_session
from ...security.deps import get_uploader_api_client, get_compute_api_client, get_current_user
from ...DataAccess.tables.__Enumeration import Role
from .DTO import (
    JobCreateDTO, JobCreatedRespDTO, JobGetRespDTO, JobStatusRespDTO,
    JobCompleteDTO, JobListRespDTO, OKRespDTO
)
from ...DataAccess.task_producer import enqueue
from ...DataAccess.tables import inference_jobs, recordings, events, users
from ...DataAccess.tables.__Enumeration import JobStatus, UploadStatus
from ...router.User.service import UserService
from ...config.path import (
    JOBS_PREFIX, JOBS_POST_CREATE_JOB, JOBS_GET_GET_JOB, JOBS_GET_GET_JOB_STATUS
)

jobs_router = APIRouter(prefix=JOBS_PREFIX, tags=["jobs"])


def create_uuid7() -> uuid.UUID:
    return uuid.UUID(str(uuidu.uuid7()))


def _parse_iso_dt(s: str | None):
    """將 ISO 字串(含 Z) 轉 datetime；失敗回 None。"""
    if not s:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


@jobs_router.post(JOBS_POST_CREATE_JOB, response_model=JobCreatedRespDTO, status_code=status.HTTP_201_CREATED)
async def create_job(body: JobCreateDTO, db: AsyncSession = Depends(get_session), api_key = Depends(get_uploader_api_client)):
    """建立新的推論任務。
    
    為影片輸入建立 recording 記錄，建立 pending 狀態的 job，
    並將任務投遞到 Celery 進行非同步處理。
    
    Args:
        body: 任務建立請求資料
        db: 資料庫會話
        api_key: API Key 驗證（依賴注入）
        
    Returns:
        JobCreatedRespDTO: 包含 job_id 和 trace_id
        
    Raises:
        HTTPException: 當輸入類型為 video 但缺少 user_id 時
    """
    trace_id: str = body.trace_id or str(create_uuid7())
    params_json = jsonable_encoder(body.params)

    # 注意：AsyncSession 預設 autobegin=True，任何 db.execute 都會自動開 transaction。
    # 因此 create_job 的所有 DB 操作必須收斂到單一個 begin()，避免 nested begin 造成
    # "A transaction is already begun on this Session."
    async with db.begin():
        # 獲取使用者的 LLM API Key（僅對需要 LLM 處理的 job 類型）
        # 目前只有 video_description_extraction 需要 LLM
        requires_llm = body.type == "video_description_extraction"
        
        if requires_llm:
            if not body.params.user_id:
                raise HTTPException(
                    status_code=400,
                    detail="user_id 是必需的（用於確定使用的 LLM API Key）"
                )
            
            user_service = UserService()
            user_result = await db.execute(
                select(users.Table).where(users.Table.id == body.params.user_id)
            )
            current_user = user_result.scalar_one_or_none()
            
            if not current_user:
                raise HTTPException(
                    status_code=404,
                    detail=f"使用者 {body.params.user_id} 不存在"
                )

            llm_provider, llm_model, llm_api_key = await user_service.get_user_llm_config(db, current_user)
            if llm_api_key is None:
                llm_api_key = await user_service.get_default_google_api_key(db)

            if llm_api_key:
                params_json["google_api_key"] = llm_api_key
                print(f"[Jobs] 已為使用者 {body.params.user_id} 設定 LLM API Key")
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"使用者 {body.params.user_id} 沒有可用的 LLM API Key（請設定自己的 API Key 或確保系統預設 API Key 已設定）"
                )

        # 建立 recordings（僅 video 輸入）
        recording_id: uuid.UUID | None = None
        if body.input_type == "video":
            # s3_key 去重
            res = await db.execute(
                select(recordings.Table).where(recordings.Table.s3_key == body.input_url)
            )
            rec = res.scalar_one_or_none()

            if rec:
                recording_id = rec.id
            else:
                if body.params.user_id is None:
                    raise HTTPException(status_code=400, detail="params.user_id is required for video inputs")

                rec = recordings.Table(
                    user_id=body.params.user_id,
                    camera_id=body.params.camera_id,
                    s3_key=body.input_url,
                    upload_status=UploadStatus.success,
                )
                db.add(rec)
                await db.flush()
                recording_id = rec.id

            if not params_json.get("video_id"):
                params_json["video_id"] = str(recording_id)

        # 建立 job（pending）
        job = inference_jobs.Table(
            type=body.type,
            input_type=body.input_type,
            input_url=body.input_url,
            status=JobStatus.pending,
            trace_id=trace_id,
            params=params_json,
        )
        db.add(job)
        await db.flush()  # 取得 job.id

    # 投遞 Celery（交易外）
    task_name = {
        "video_description_extraction": "tasks.video_description_extraction",
    }.get(body.type)

    if not task_name:
        # 這裡開一個獨立交易把 job 標成 failed
        async with db.begin():
            await db.execute(
                update(inference_jobs.Table)
                .where(inference_jobs.Table.id == job.id)
                .values(status=JobStatus.failed, error_message="Unsupported job type")
            )
        raise HTTPException(status_code=400, detail=f"Unsupported job type: {body.type}")

    payload = {
        "job_id": str(job.id),
        "type": job.type,
        "input_type": job.input_type,
        "input_url": job.input_url,
        "params": params_json,
        "trace_id": trace_id,
    }

    try:
        enqueue(task_name, kwargs={"job": payload}, headers={"X-Trace-Id": trace_id})
    except Exception as e:
        # 若投遞失敗，把 job 標為 failed
        async with db.begin():
            await db.execute(
                update(inference_jobs.Table)
                .where(inference_jobs.Table.id == job.id)
                .values(status=JobStatus.failed, error_message=str(e))
            )
        # 回傳 503，並保留 traceback
        raise HTTPException(status_code=503, detail=f"Enqueue failed: {e}") from e

    return JobCreatedRespDTO(
        job_id=job.id,
        trace_id=trace_id,
        status=JobStatus.pending.value
    )



@jobs_router.get(JOBS_GET_GET_JOB, response_model=JobGetRespDTO)
async def get_job(job_id: str, db: AsyncSession = Depends(get_session), current_user = Depends(get_current_user)):
    """取得 Job 狀態與結果"""
    try:
        jid = uuid.UUID(job_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job_id")

    stmt = select(inference_jobs.Table).where(inference_jobs.Table.id == jid)
    result = await db.execute(stmt)
    job: Optional[inference_jobs.Table] = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # 權限檢查：非管理員只能查看自己相關的任務
    if current_user.role != Role.admin:
        # 檢查任務是否與當前使用者相關
        job_params = job.params or {}
        job_user_id = job_params.get("user_id")
        
        if job_user_id != current_user.id:
            raise HTTPException(status_code=403, detail="沒有權限查看此任務")

    return JobGetRespDTO(
        job_id=job.id,
        type=job.type,
        status=job.status.value if hasattr(job.status, "value") else str(job.status),
        input_type=job.input_type,
        input_url=job.input_url,
        output_url=job.output_url,
        trace_id=job.trace_id,
        duration=job.duration,
        error_code=job.error_code,
        error_message=job.error_message,
        params=job.params,
        metrics=job.metrics,
    )


@jobs_router.get(JOBS_GET_GET_JOB_STATUS, response_model=JobStatusRespDTO)
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_session), current_user = Depends(get_current_user)):
    """取得 Job 狀態"""
    try:
        jid = uuid.UUID(job_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job_id")

    # 先獲取完整的 job 資訊以進行權限檢查
    stmt = select(inference_jobs.Table).where(inference_jobs.Table.id == jid)
    result = await db.execute(stmt)
    job: Optional[inference_jobs.Table] = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # 權限檢查：非管理員只能查看自己相關的任務
    if current_user.role != Role.admin:
        job_params = job.params or {}
        job_user_id = job_params.get("user_id")
        
        if job_user_id != current_user.id:
            raise HTTPException(status_code=403, detail="沒有權限查看此任務")

    return JobStatusRespDTO(status=job.status.value)


@jobs_router.get("/", response_model=JobListRespDTO)
async def list_jobs(
    status_filter: Optional[str] = Query(default=None, description="篩選任務狀態"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
    current_user = Depends(get_current_user)
):
    """取得任務列表（支援分頁和狀態篩選）"""
    
    # 構建查詢條件
    conditions = []
    
    # 權限控制：使用者 ID 過濾
    if current_user.role == Role.admin:
        # 管理員可以查看所有任務
        pass
    else:
        # 一般使用者只能查看自己的任務
        # 使用 JSON 查詢來篩選 params.user_id
        conditions.append(
            func.json_extract(inference_jobs.Table.params, "$.user_id") == current_user.id
        )
    
    # 狀態篩選
    if status_filter:
        try:
            job_status = JobStatus(status_filter)
            conditions.append(inference_jobs.Table.status == job_status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter}")
    
    # 查詢任務
    base_query = select(inference_jobs.Table)
    if conditions:
        base_query = base_query.where(and_(*conditions))
    
    # 分頁查詢
    stmt_items = base_query.order_by(inference_jobs.Table.created_at.desc()).offset((page - 1) * size).limit(size)
    stmt_total = select(func.count()).select_from(base_query.subquery())
    
    rows = (await db.execute(stmt_items)).scalars().all()
    total = (await db.execute(stmt_total)).scalar_one()
    
    # 轉換為 DTO
    items = []
    for job in rows:
        items.append(JobGetRespDTO(
            job_id=job.id,
            type=job.type,
            status=job.status.value if hasattr(job.status, "value") else str(job.status),
            input_type=job.input_type,
            input_url=job.input_url,
            output_url=job.output_url,
            trace_id=job.trace_id,
            duration=job.duration,
            error_code=job.error_code,
            error_message=job.error_message,
            params=job.params,
            metrics=job.metrics,
        ))
    
    return JobListRespDTO(
        items=items,
        total=total,
        page=page,
        size=size,
        page_total=total // size + (1 if total % size > 0 else 0),
    )


@jobs_router.patch("/{job_id}/update_status", response_model=JobStatusRespDTO)
async def update_job_status(job_id: str, new_status: JobStatus, db: AsyncSession = Depends(get_session)):
    """更新 Job 狀態（僅限內部使用）"""
    try:
        jid = uuid.UUID(job_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job_id")

    async with db.begin():
        stmt = (
            update(inference_jobs.Table)
            .where(inference_jobs.Table.id == jid)
            .values(status=new_status)
            .returning(inference_jobs.Table.status)
        )
        result = await db.execute(stmt)
        updated_status: Optional[JobStatus] = result.scalar_one_or_none()
        if not updated_status:
            raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusRespDTO(status=updated_status.value)


@jobs_router.post("/{job_id}/complete", response_model=OKRespDTO)
async def complete_job(job_id: str, body: JobCompleteDTO, db: AsyncSession = Depends(get_session), api_key = Depends(get_compute_api_client)):
    """
    Job 完成後的回傳：
    1) 更新 job（狀態/錯誤/度量）
    2) 若成功，更新 recordings（is_processed/start_time/end_time）
    """
    # 驗證 path 與 body 的 job_id 一致
    try:
        jid_path = uuid.UUID(job_id)
        jid_body = uuid.UUID(str(body.job_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job_id")

    if jid_path != jid_body:
        raise HTTPException(status_code=400, detail="Path job_id and body.job_id mismatch")

    # 轉 Enum 與時間：直接使用 JobStatus enum 內的字（正規化已在 DTO 做 strip/lower）
    new_status = body.status

    vstart = _parse_iso_dt(body.video_start_time)
    vend = _parse_iso_dt(body.video_end_time)

    async with db.begin():
        # (1) 更新 job（並確認 job 存在）
        res_upd = await db.execute(
            update(inference_jobs.Table)
            .where(inference_jobs.Table.id == jid_body)
            .values(
                status=new_status,
                error_code=body.error_code,
                error_message=body.error_message,
                duration=body.duration,
                metrics=body.metrics,
            )
            .returning(inference_jobs.Table.id)
        )
        updated_id = res_upd.scalar_one_or_none()
        if not updated_id:
            raise HTTPException(status_code=404, detail="Job not found")

        # (1.5) 寫入 Token 使用量（Compute 來源）
        # 只要 metrics 帶有 LLM token 資訊，就會被統計進使用者的 Token 使用量
        try:
            res_params = await db.execute(
                select(inference_jobs.Table.params, inference_jobs.Table.type).where(inference_jobs.Table.id == jid_body)
            )
            row = res_params.first()
            job_params = (row[0] if row else None) or {}
            job_type = (row[1] if row else None) or None
            user_id = job_params.get("user_id")

            metrics = body.metrics or {}
            prompt_tokens = metrics.get("llm_prompt_tokens")
            completion_tokens = metrics.get("llm_completion_tokens")
            total_tokens = metrics.get("llm_total_tokens")

            if user_id and (prompt_tokens is not None or completion_tokens is not None or total_tokens is not None):
                from ...utils.llm_usage import log_llm_usage
                usage = {
                    "prompt_tokens": int(prompt_tokens or 0),
                    "completion_tokens": int(completion_tokens or 0),
                    "total_tokens": int(total_tokens or (int(prompt_tokens or 0) + int(completion_tokens or 0))),
                }
                provider = metrics.get("llm_provider")
                model_name = metrics.get("llm_model") or metrics.get("llm_model_name")
                await log_llm_usage(
                    db,
                    user_id=int(user_id),
                    source="compute",
                    provider=str(provider) if provider else None,
                    model_name=str(model_name) if model_name else None,
                    usage=usage,
                    assistant_replies=0,
                    trace_id=body.trace_id,
                    meta={"job_id": str(jid_body), "job_type": job_type},
                )
        except Exception as e:
            print(f"[Jobs] 記錄 compute token 使用量失敗: {e}")

        # (2) 若成功 → 更新 recordings 與事件表
        if new_status == JobStatus.success:
            # 取 job.params 拿 video_id
            res = await db.execute(
                select(inference_jobs.Table.params).where(inference_jobs.Table.id == jid_body)
            )
            job_params: Optional[dict] = res.scalar_one_or_none() or {}
            video_id = job_params.get("video_id")
            if not video_id:
                # 不讓 /complete 直接失敗：改成把 job 標記 failed，避免前端卡在 processing
                await db.execute(
                    update(inference_jobs.Table)
                    .where(inference_jobs.Table.id == jid_body)
                    .values(
                        status=JobStatus.failed,
                        error_code="MISSING_VIDEO_ID",
                        error_message="video_id not found in job params (cannot update recordings/events)",
                    )
                )
                return OKRespDTO()

            try:
                vid = uuid.UUID(str(video_id))
            except Exception:
                await db.execute(
                    update(inference_jobs.Table)
                    .where(inference_jobs.Table.id == jid_body)
                    .values(
                        status=JobStatus.failed,
                        error_code="INVALID_VIDEO_ID",
                        error_message="Invalid video_id in job params (cannot update recordings/events)",
                    )
                )
                return OKRespDTO()

            await db.execute(
                update(recordings.Table)
                .where(recordings.Table.id == vid)
                .values(
                    is_processed=True,
                    duration=body.metrics.get("video_duration_sec") if body.metrics else None,
                    start_time=vstart,
                    end_time=vend
                )
            )
            # events 新增
            """
            結構範例：
                {
                    "job_id": "test_job",
                    "trace_id": "test_trace",
                    "status": "success",
                    "video_start_time": null,
                    "video_end_time": null,
                    "error_code": null,
                    "error_message": null,
                    "duration": 15.466666666666667, # 任務執行時間
                    "metrics": {
                        "video_fps": 30.0,
                        "video_total_frames": 254,
                        "video_duration_sec": 8.466666666666667,
                        "target_fps": 2,
                        "effective_fps": 2.0,
                        "extracted_frames": 17,
                        "possible_extracts": 16,
                        "frames_total": 17,
                        "frames_not_blurry": 5,
                        "frames_significant": 17,
                        "frames_captioned": 5,
                        "frames_kept_for_llm": 5,
                        "not_blurry_rate": 0.29411764705882354,
                        "significant_rate": 1.0,
                        "captioned_rate": 0.29411764705882354,
                        "llm_events_count": 1,
                        "index_clamp_count": 0
                    },
                    "events": [
                        {
                            "start_time": 0.0,
                            "end_time": 7.5,
                            "summary": "在停車場和街道上，有人騎著自行車，場景為室外。",
                            "objects": [
                                "汽車",
                                "自行車",
                                "停車場",
                                "街道"
                            ],
                            "scene": "室外",
                            "action": "騎自行車"
                        }
                    ]
                }
            """
            # 取得 recording 的 user_id / s3_key（後續 events、縮圖都會用到）
            res_rec = await db.execute(
                select(recordings.Table.user_id, recordings.Table.s3_key).where(recordings.Table.id == vid)
            )
            rec_row = res_rec.first()
            recording_user_id = rec_row[0] if rec_row else None
            recording_s3_key = rec_row[1] if rec_row else None

            # start_time 儲存UTC時間
            if body.events:
                if not recording_user_id:
                    await db.execute(
                        update(inference_jobs.Table)
                        .where(inference_jobs.Table.id == jid_body)
                        .values(
                            status=JobStatus.failed,
                            error_code="RECORDING_USER_NOT_FOUND",
                            error_message="recording user_id not found (cannot create events)",
                        )
                    )
                    return OKRespDTO()
                
                for event in body.events:
                    ev = events.Table(
                        user_id=recording_user_id,  # 🔧 修復：添加 user_id
                        recording_id=vid,
                        action=event.get("action"),
                        scene=event.get("scene"),
                        summary=event.get("summary"),
                        objects=event.get("objects"),
                        embedding=event.get("embedding"), # 10/20/2025 Add embedding
                        start_time=vstart + timedelta(seconds=event.get("start_time")) if vstart and event.get("start_time") is not None else None,
                        duration=event.get("end_time") - event.get("start_time") if event.get("end_time") is not None and event.get("start_time") is not None else None
                    )
                    db.add(ev)
                
                # 提交事件到資料庫
                await db.commit()
                
                # 如果事件中沒有 embedding,則觸發 embedding 生成任務
                has_embedding = any(event.get("embedding") for event in body.events)
                if not has_embedding:
                    try:
                        from ...DataAccess.task_producer import enqueue

                        # 建立 inference_jobs 追蹤（embedding_generation）
                        emb_job = inference_jobs.Table(
                            type="embedding_generation",
                            status=JobStatus.pending,
                            input_type="recording",
                            input_url=str(vid),
                            output_url=None,
                            trace_id=body.trace_id,
                            params={
                                "user_id": int(recording_user_id) if recording_user_id is not None else None,
                                "recording_id": str(vid),
                                "progress": 0.0,
                            },
                            metrics=None,
                        )
                        db.add(emb_job)
                        await db.commit()
                        await db.refresh(emb_job)

                        enqueue("tasks.generate_embeddings_for_recording", {
                            "recording_id": str(vid),
                            "job_id": str(emb_job.id),
                        })
                        print(f"[Job] 已觸發 embedding 生成任務: recording_id={vid} job_id={emb_job.id}")
                    except Exception as e:
                        print(f"[Job] 觸發 embedding 生成任務失敗: {e}")
                
            # 縮圖生成已併入 ComputeServer 的 videosprocessing（同一支任務使用記憶體幀直接產生縮圖並回寫）
            # 因此這裡不再 enqueue tasks.generate_video_thumbnail，避免重複工作與競態。
    
    return OKRespDTO()
