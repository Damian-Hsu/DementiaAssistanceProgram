# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional
import uuid_utils as uuidu
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update, select

from ...DataAccess.Connect import get_session
from .DOT import JobCreateDTO, JobCreatedRespDTO, JobGetRespDTO, JobStatusRespDTO, JobCompleteDTO
from ...DataAccess.task_producer import enqueue
from ...DataAccess.tables import inference_jobs
from ...DataAccess.tables.__Enumeration import JobStatus
from ...config.path import (JOBS_PREFIX,
                            JOBS_POST_CREATE_JOB,
                            JOBS_GET_GET_JOB,
                            JOBS_GET_GET_JOB_STATUS)

jobs_router = APIRouter(prefix=JOBS_PREFIX, tags=["jobs"])

def create_uuid7() -> uuid.UUID:
    uuid_util = uuidu.uuid7()
    return uuid.UUID(str(uuid_util))


@jobs_router.post(JOBS_POST_CREATE_JOB, response_model=JobCreatedRespDTO, status_code=status.HTTP_201_CREATED)
async def create_job(body: JobCreateDTO, db: AsyncSession = Depends(get_session)):
    """
    建立一個新 Job:
    1. 在 DB 建立紀錄 (status=pending)
    2. 投遞 Celery 任務到 Redis
    3. 回傳 job_id 給前端
    """
    # --- 1) 確定 trace_id ---
    trace_id = body.trace_id or create_uuid7()

    # --- 2) DB 新增 job ---
    job = inference_jobs.Table(
        type=body.type,
        input_type=body.input_type,
        input_url=body.input_url,
        status=JobStatus.pending,
        trace_id=str(trace_id),
        params=body.params,
    )
    try:
        db.add(job)
        await db.commit()
        await db.refresh(job)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DB insert failed: {e}",
        )

    # --- 3) 投遞 Celery ---
    task_name = {
        "video_description_extraction": "tasks.video_description_extraction",
        # 之後可以在這裡新增更多對映
    }.get(body.type)

    if not task_name:
        await db.execute(
            update(inference_jobs.Table)
            .where(inference_jobs.Table.id == job.id)
            .values(status=JobStatus.failed, error_message="Unsupported job type")
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported job type: {body.type}",
        )

    payload = {
        "job_id": str(job.id),
        "type": job.type,
        "input_type": job.input_type,
        "input_url": job.input_url,
        "params": job.params,
        "trace_id": str(job.trace_id),
    }

    try:
        enqueue(
            task_name,
            kwargs={"job": payload},
            headers={"X-Trace-Id": str(trace_id)},
        )
    except Exception as e:
        await db.execute(
            update(inference_jobs.Table)
            .where(inference_jobs.Table.id == job.id)
            .values(status=JobStatus.failed, error_message=str(e))
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Enqueue failed: {e}",
        )

    # --- 4) 回應 ---
    return JobCreatedRespDTO(
        job_id=job.id,
        trace_id=str(trace_id),
        status=JobStatus.pending,
    )

@jobs_router.get(JOBS_GET_GET_JOB, response_model=JobGetRespDTO)
async def get_job(job_id: str, db: AsyncSession = Depends(get_session)):
    """
    取得 Job 狀態與結果
    """
    stmt = select(inference_jobs.Table).where(inference_jobs.Table.id == job_id)
    result = await db.execute(stmt)
    job: Optional[inference_jobs.Table] = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    return JobGetRespDTO(
        job_id=str(job.id),
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
    """
    取得 Job 狀態
    """
    stmt = select(inference_jobs.Table.status).where(inference_jobs.Table.id == job_id)
    result = await db.execute(stmt)
    status_result: Optional[JobStatus] = result.scalar_one_or_none()
    
    if not status_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    return JobStatusRespDTO(status=status_result.value)

@jobs_router.patch("/{job_id}/update_status", response_model=JobStatusRespDTO)
async def update_job_status(job_id: str, new_status: JobStatus, db: AsyncSession = Depends(get_session)):
    """
    更新 Job 狀態（僅限內部使用）
    """
    stmt = (
        update(inference_jobs.Table)
        .where(inference_jobs.Table.id == job_id)
        .values(status=new_status)
        .returning(inference_jobs.Table.status)
    )
    result = await db.execute(stmt)
    updated_status: Optional[JobStatus] = result.scalar_one_or_none()   
    if not updated_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    await db.commit()

    return JobStatusRespDTO(status=updated_status.value)

# job完成後的回傳存到對應的event

@jobs_router.post("/{job_id}/complete")
async def complete_job(body:JobCompleteDTO ,db: AsyncSession = Depends(get_session)):
    """
    Job 完成後的回傳
    收到結構為 JobCompleteDTO 的資料，此程式要更新video
    """
    
    