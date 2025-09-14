# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional
import uuid
from datetime import datetime, timedelta
import uuid_utils as uuidu
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import update, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...DataAccess.Connect import get_session
from .DTO import (
    JobCreateDTO, JobCreatedRespDTO, JobGetRespDTO, JobStatusRespDTO,
    JobCompleteDTO, OKRespDTO
)
from ...DataAccess.task_producer import enqueue
from ...DataAccess.tables import inference_jobs, recordings, events
from ...DataAccess.tables.__Enumeration import JobStatus, UploadStatus
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
async def create_job(body: JobCreateDTO, db: AsyncSession = Depends(get_session)):
    trace_id: str = body.trace_id or str(create_uuid7())
    params_json = jsonable_encoder(body.params)

    # 1) 建 recordings（僅 video）
    async with db.begin():
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
                    # 讓 FastAPI 處理這個 HTTP 例外，無需外層再捕捉一次
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

        # 2) 建 job（pending）
        job = inference_jobs.Table(
            type=body.type,
            input_type=body.input_type,
            input_url=body.input_url,
            status=JobStatus.pending,
            trace_id=trace_id,
            params=params_json,
        )
        db.add(job)
        await db.flush()  # 拿到 job.id

    # 3) 投遞 Celery（交易外）
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
async def get_job(job_id: str, db: AsyncSession = Depends(get_session)):
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
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_session)):
    """取得 Job 狀態"""
    try:
        jid = uuid.UUID(job_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid job_id")

    stmt = select(inference_jobs.Table.status).where(inference_jobs.Table.id == jid)
    result = await db.execute(stmt)
    status_result: Optional[JobStatus] = result.scalar_one_or_none()

    if not status_result:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusRespDTO(status=status_result.value)


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
async def complete_job(job_id: str, body: JobCompleteDTO, db: AsyncSession = Depends(get_session)):
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

    # 轉 Enum 與時間
    try:
        new_status = JobStatus(body.status)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")

    vstart = _parse_iso_dt(body.video_start_time)
    vend = _parse_iso_dt(body.video_end_time)

    async with db.begin():
        # (1) 更新 job
        await db.execute(
            update(inference_jobs.Table)
            .where(inference_jobs.Table.id == jid_body)
            .values(
                status=new_status,
                error_code=body.error_code,
                error_message=body.error_message,
                duration=body.duration,
                metrics=body.metrics,
            )
        )

        # (2) 若成功 → 更新 recordings 與事件表
        if new_status == JobStatus.success:
            # 取 job.params 拿 video_id
            res = await db.execute(
                select(inference_jobs.Table.params).where(inference_jobs.Table.id == jid_body)
            )
            job_params: Optional[dict] = res.scalar_one_or_none() or {}
            video_id = job_params.get("video_id")
            if not video_id:
                raise HTTPException(status_code=400, detail="video_id not found in job params")

            try:
                vid = uuid.UUID(str(video_id))
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid video_id in job params")

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
            # start_time 儲存UTC時間
            if body.events:
                for event in body.events:
                    ev = events.Table(
                        recording_id=vid,
                        action=event.get("action"),
                        scene=event.get("scene"),
                        summary=event.get("summary"),
                        objects=event.get("objects"),
                        start_time=vstart + timedelta(seconds=event.get("start_time")) if vstart and event.get("start_time") is not None else None,
                        duration=event.get("end_time") - event.get("start_time") if event.get("end_time") is not None and event.get("start_time") is not None else None
                    )
                    db.add(ev)
    return OKRespDTO()
