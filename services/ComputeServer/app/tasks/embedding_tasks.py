"""
Embedding 生成任務
在視頻描述完成後,為 events 生成 embedding
"""
import os
import logging
import json
import uuid
from typing import List, Dict, Any
from celery import Task
from ..main import app
from sqlalchemy import create_engine, select, update, text
from sqlalchemy.orm import Session
from ..libs.RAG import RAGModel

# 設置日誌
logger = logging.getLogger(__name__)

# 資料庫連接
DB_HOST = os.getenv('DB_HOST', 'postgres')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'dementia')
DB_USER = os.getenv('DB_SUPERUSER', 'postgres')
DB_PASSWORD = os.getenv('DB_SUPERPASS', 'default_password')

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL)

def _update_inference_job(
    job_id: str,
    *,
    status: str,
    progress: float | None = None,
    error_message: str | None = None,
    output_url: str | None = None,
    params_patch: dict | None = None,
    metrics_patch: dict | None = None,
) -> None:
    """Compute 端直接更新 inference_jobs（避免再走 API）。best-effort。"""
    if not job_id:
        return
    try:
        with Session(engine) as session:
            row = session.execute(
                text("SELECT params, metrics FROM inference_jobs WHERE id = :id"),
                {"id": job_id},
            ).mappings().first()
            params = dict(row["params"] or {}) if row else {}
            metrics = dict(row["metrics"] or {}) if row else {}

            if params_patch:
                params.update(params_patch)
            if progress is not None:
                params["progress"] = max(0.0, min(100.0, float(progress)))
            if metrics_patch:
                metrics.update(metrics_patch)

            session.execute(
                text("""
                    UPDATE inference_jobs
                    SET status = :status,
                        error_message = :error_message,
                        output_url = COALESCE(:output_url, output_url),
                        params = CAST(:params AS jsonb),
                        metrics = CAST(:metrics AS jsonb),
                        updated_at = NOW()
                    WHERE id = :id
                """),
                {
                    "id": job_id,
                    "status": status,
                    "error_message": error_message,
                    "output_url": output_url,
                    "params": json.dumps(params),
                    "metrics": json.dumps(metrics),
                },
            )
            session.commit()
    except Exception as e:
        logger.warning(f"[EmbeddingTask] 更新 inference_jobs 失敗: job_id={job_id} err={e}")


class EmbeddingGenerationTask(Task):
    """Embedding 生成任務基類"""
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """任務失敗時的回調"""
        logger.error(f"Embedding 生成任務失敗: {exc}")
        logger.error(f"錯誤信息: {einfo}")


@app.task(bind=True, base=EmbeddingGenerationTask, name="tasks.generate_embeddings_for_recording")
def generate_embeddings_for_recording(self, recording_id: str, job_id: str | None = None) -> Dict[str, Any]:
    """
    為指定錄影的所有事件生成 embedding
    
    Args:
        recording_id: 錄影 ID
    
    Returns:
        包含處理結果的字典
    """
    logger.info(f"開始為錄影 {recording_id} 生成 embeddings")
    if job_id:
        _update_inference_job(job_id, status="processing", progress=1.0, params_patch={"recording_id": recording_id})
    
    try:
        # 獲取 RAG 模型實例 (單例)
        rag = RAGModel.get_instance()
        
        # 查詢該錄影的所有事件
        with Session(engine) as session:
            result = session.execute(
                text("""
                    SELECT id, summary
                    FROM events
                    WHERE recording_id = :recording_id
                    AND embedding IS NULL
                    AND summary IS NOT NULL
                    AND summary != ''
                """),
                {"recording_id": recording_id}
            )
            
            events = result.fetchall()
            
            if not events:
                logger.info(f"錄影 {recording_id} 沒有需要生成 embedding 的事件")
                if job_id:
                    _update_inference_job(
                        job_id,
                        status="success",
                        progress=100.0,
                        metrics_patch={"processed_count": 0, "total_events": 0},
                    )
                return {
                    "recording_id": recording_id,
                    "processed_count": 0,
                    "status": "no_events"
                }
            
            # 批量生成 embeddings
            processed_count = 0
            for event_row in events:
                event_id = event_row.id
                summary = event_row.summary
                
                try:
                    # 生成 embedding
                    embedding = rag.encode([f"passage: {summary}"])[0]
                    embedding_list = embedding.tolist()
                    
                    # 更新到資料庫
                    session.execute(
                        text("""
                            UPDATE events
                            SET embedding = :embedding,
                                updated_at = NOW()
                            WHERE id = :event_id
                        """),
                        {
                            "event_id": str(event_id),
                            "embedding": embedding_list
                        }
                    )
                    processed_count += 1
                    # 進度回報（粗略）
                    if job_id and len(events) > 0:
                        _update_inference_job(
                            job_id,
                            status="processing",
                            progress=1.0 + (processed_count / max(1, len(events))) * 98.0,
                            metrics_patch={"processed_count": processed_count, "total_events": len(events)},
                        )
                    
                except Exception as e:
                    logger.error(f"為事件 {event_id} 生成 embedding 失敗: {e}")
                    continue
            
            # 提交事務
            session.commit()
            
            # 更新錄影的 embedding 標記
            session.execute(
                text("""
                    UPDATE recordings
                    SET is_embedding = TRUE,
                        updated_at = NOW()
                    WHERE id = :recording_id
                """),
                {"recording_id": recording_id}
            )
            session.commit()
            
            logger.info(f"成功為錄影 {recording_id} 的 {processed_count} 個事件生成 embeddings")
            if job_id:
                _update_inference_job(
                    job_id,
                    status="success",
                    progress=100.0,
                    metrics_patch={"processed_count": processed_count, "total_events": len(events)},
                )
            
            return {
                "recording_id": recording_id,
                "processed_count": processed_count,
                "total_events": len(events),
                "status": "success"
            }
    
    except Exception as e:
        logger.error(f"生成 embeddings 時發生錯誤: {e}", exc_info=True)
        if job_id:
            _update_inference_job(job_id, status="failed", progress=100.0, error_message=str(e))
        raise


@app.task(bind=True, name="tasks.generate_embedding_for_event")
def generate_embedding_for_event(self, event_id: str, summary: str, job_id: str | None = None) -> Dict[str, Any]:
    """
    為單個事件生成 embedding
    
    Args:
        event_id: 事件 ID
        summary: 事件摘要文本
    
    Returns:
        包含 embedding 的字典
    """
    logger.info(f"為事件 {event_id} 生成 embedding")
    if job_id:
        _update_inference_job(job_id, status="processing", progress=10.0, params_patch={"event_id": event_id})
    
    try:
        # 獲取 RAG 模型實例
        rag = RAGModel.get_instance()
        
        # 生成 embedding
        embedding = rag.encode([f"passage: {summary}"])[0]
        embedding_list = embedding.tolist()
        
        # 更新到資料庫
        with Session(engine) as session:
            session.execute(
                text("""
                    UPDATE events
                    SET embedding = :embedding,
                        updated_at = NOW()
                    WHERE id = :event_id
                """),
                {
                    "event_id": event_id,
                    "embedding": embedding_list
                }
            )
            session.commit()
        
        logger.info(f"成功為事件 {event_id} 生成 embedding")
        if job_id:
            _update_inference_job(job_id, status="success", progress=100.0)
        
        return {
            "event_id": event_id,
            "embedding": embedding_list,
            "status": "success"
        }
    
    except Exception as e:
        logger.error(f"為事件 {event_id} 生成 embedding 失敗: {e}", exc_info=True)
        if job_id:
            _update_inference_job(job_id, status="failed", progress=100.0, error_message=str(e))
        raise


@app.task(bind=True, base=EmbeddingGenerationTask, name="tasks.generate_diary_embeddings")
def generate_diary_embeddings(self, diary_id: str, chunks: List[str], job_id: str | None = None, user_id: int | None = None) -> Dict[str, Any]:
    """為指定 diary 產生 chunks embeddings，寫入 diary_chunks（以 diary_id 作為外鍵）。"""
    logger.info(f"開始為日記 {diary_id} 生成 diary_chunks embeddings (chunks={len(chunks) if chunks else 0})")
    if job_id:
        _update_inference_job(job_id, status="processing", progress=1.0, params_patch={"diary_id": diary_id, "user_id": user_id})

    try:
        if not diary_id or not chunks:
            if job_id:
                _update_inference_job(job_id, status="failed", progress=100.0, error_message="missing diary_id or chunks")
            raise ValueError("missing diary_id or chunks")

        rag = RAGModel.get_instance()
        total = len(chunks)

        with Session(engine) as session:
            # 清除舊 chunks（重新生成）
            session.execute(
                text("DELETE FROM diary_chunks WHERE diary_id = :did"),
                {"did": diary_id},
            )

            processed = 0
            for idx, chunk in enumerate(chunks):
                # 生成 embedding
                emb = rag.encode([f"passage: {chunk}"])[0]
                emb_list = emb.tolist() if hasattr(emb, "tolist") else list(emb)
                # pgvector：用文字格式 + cast，避免 driver 不支援 list -> vector
                emb_str = "[" + ",".join(str(float(x)) for x in emb_list) + "]"

                session.execute(
                    text("""
                        INSERT INTO diary_chunks (id, diary_id, chunk_text, chunk_index, embedding, is_processed)
                        VALUES (:id, :did, :txt, :idx, CAST(:emb AS vector), TRUE)
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "did": diary_id,
                        "txt": chunk,
                        "idx": int(idx),
                        "emb": emb_str,
                    },
                )

                processed += 1
                if job_id:
                    _update_inference_job(
                        job_id,
                        status="processing",
                        progress=1.0 + (processed / max(1, total)) * 98.0,
                        metrics_patch={"chunks_total": total, "chunks_processed": processed},
                    )

            session.commit()

        if job_id:
            _update_inference_job(
                job_id,
                status="success",
                progress=100.0,
                metrics_patch={"chunks_total": total, "chunks_processed": total},
            )

        return {"diary_id": diary_id, "chunks_count": total, "status": "success"}

    except Exception as e:
        logger.error(f"生成 diary embeddings 失敗: {e}", exc_info=True)
        if job_id:
            _update_inference_job(job_id, status="failed", progress=100.0, error_message=str(e))
        raise

