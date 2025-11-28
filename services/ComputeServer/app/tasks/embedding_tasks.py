"""
Embedding 生成任務
在視頻描述完成後,為 events 生成 embedding
"""
import os
import logging
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


class EmbeddingGenerationTask(Task):
    """Embedding 生成任務基類"""
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """任務失敗時的回調"""
        logger.error(f"Embedding 生成任務失敗: {exc}")
        logger.error(f"錯誤信息: {einfo}")


@app.task(bind=True, base=EmbeddingGenerationTask, name="tasks.generate_embeddings_for_recording")
def generate_embeddings_for_recording(self, recording_id: str) -> Dict[str, Any]:
    """
    為指定錄影的所有事件生成 embedding
    
    Args:
        recording_id: 錄影 ID
    
    Returns:
        包含處理結果的字典
    """
    logger.info(f"開始為錄影 {recording_id} 生成 embeddings")
    
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
            
            return {
                "recording_id": recording_id,
                "processed_count": processed_count,
                "total_events": len(events),
                "status": "completed"
            }
    
    except Exception as e:
        logger.error(f"生成 embeddings 時發生錯誤: {e}", exc_info=True)
        raise


@app.task(bind=True, name="tasks.generate_embedding_for_event")
def generate_embedding_for_event(self, event_id: str, summary: str) -> Dict[str, Any]:
    """
    為單個事件生成 embedding
    
    Args:
        event_id: 事件 ID
        summary: 事件摘要文本
    
    Returns:
        包含 embedding 的字典
    """
    logger.info(f"為事件 {event_id} 生成 embedding")
    
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
        
        return {
            "event_id": event_id,
            "embedding": embedding_list,
            "status": "completed"
        }
    
    except Exception as e:
        logger.error(f"為事件 {event_id} 生成 embedding 失敗: {e}", exc_info=True)
        raise

