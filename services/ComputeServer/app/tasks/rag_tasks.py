from ..main import app
from ..libs.RAG import RAGModel, create_bm25, bm25_retrieve, reciprocal_rank_fusion
import numpy as np
import os
import json
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# DB 連線（用於更新 inference_jobs）
DB_HOST = os.getenv('DB_HOST', 'postgres')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'dementia')
DB_USER = os.getenv('DB_SUPERUSER', 'postgres')
DB_PASSWORD = os.getenv('DB_SUPERPASS', 'default_password')
DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
engine = create_engine(DATABASE_URL)

def _update_inference_job(job_id: str, *, status: str, progress: float | None = None, error_message: str | None = None, metrics_patch: dict | None = None, params_patch: dict | None = None):
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
                        params = CAST(:params AS jsonb),
                        metrics = CAST(:metrics AS jsonb),
                        updated_at = NOW()
                    WHERE id = :id
                """),
                {
                    "id": job_id,
                    "status": status,
                    "error_message": error_message,
                    "params": json.dumps(params),
                    "metrics": json.dumps(metrics),
                }
            )
            session.commit()
    except Exception as e:
        logger.warning(f"[RAGTask] 更新 inference_jobs 失敗: job_id={job_id} err={e}")

@app.task(name="tasks.calculate_embedding", bind=True)
def calculate_embedding(self, text: str, is_query: bool = False, job_id: str | None = None) -> list[float]:
    rag = RAGModel.get_instance()
    if job_id:
        _update_inference_job(job_id, status="processing", progress=10.0)
    prefix = "query: " if is_query else "passage: "
    # encode returns list of embeddings, we take the first one
    embedding = rag.encode([f"{prefix}{text}"])[0]
    if job_id:
        _update_inference_job(job_id, status="success", progress=100.0)
    return embedding.tolist()

@app.task(name="tasks.suggest_vlog_highlights", bind=True)
def suggest_vlog_highlights(self, query: str, candidates: list[dict], limit: int = 20, job_id: str | None = None, user_id: int | None = None):
    """
    query: Diary text (or user query)
    candidates: List of events [{'id': str, 'text': str, 'embedding': list[float] | None}]
    limit: Number of events to recommend (Top K)
    
    Returns: List of event IDs sorted by relevance.
    """
    print(f"[RAG] 開始 AI 推薦，查詢文本: {query[:100]}...")
    print(f"[RAG] 候選事件數量: {len(candidates)}，目標數量: {limit}")
    if job_id:
        _update_inference_job(job_id, status="processing", progress=1.0, params_patch={"user_id": user_id, "limit": int(limit), "candidates_count": int(len(candidates))})
    
    if not candidates:
        print("[RAG] 沒有候選事件")
        if job_id:
            _update_inference_job(job_id, status="success", progress=100.0, metrics_patch={"result_count": 0})
        return []

    rag = RAGModel.get_instance()
    
    # 準備資料
    chunks = [c['text'] for c in candidates]
    ids = [c['id'] for c in candidates]
    
    print(f"[RAG] 候選事件文本樣本: {chunks[:3]}")
    
    # BM25 搜尋
    bm25 = create_bm25(chunks)
    bm25_scores = bm25_retrieve(query, chunks, bm25)
    
    # Rank BM25 (get indices)
    bm25_ranked_indices = np.argsort(bm25_scores)[::-1]
    bm25_ranked_ids = [ids[i] for i in bm25_ranked_indices]
    
    print(f"[RAG] BM25 已對所有 {len(bm25_ranked_ids)} 個候選事件排序")
    print(f"[RAG] BM25 前5名分數: {[bm25_scores[i] for i in bm25_ranked_indices[:5]]}")
    print(f"[RAG] BM25 前5名ID: {bm25_ranked_ids[:5]}")
    
    # 向量搜尋
    # 準備 Embeddings
    cand_embeddings = []
    missing_emb_count = 0
    for c in candidates:
        if c.get('embedding') and c['embedding']:
            # Ensure embedding is list/array
            cand_embeddings.append(c['embedding'])
        else:
            # Calculate on the fly if missing
            missing_emb_count += 1
            emb = rag.encode([f"passage: {c['text']}"])[0]
            cand_embeddings.append(emb)
    
    print(f"[RAG] 需要即時計算的 embedding 數量: {missing_emb_count}/{len(candidates)}")
            
    # Prepare Query Embedding
    query_embedding = rag.encode([f"query: {query}"])[0]
    
    # Similarity
    # similarity returns a matrix (1, N) if query is 1.
    sim_scores = rag.similarity([query_embedding], cand_embeddings)[0]
    
    # Rank Vector
    # sim_scores is tensor/array.
    if hasattr(sim_scores, 'numpy'):
        sim_scores_array = sim_scores.numpy()
    else:
        sim_scores_array = np.array(sim_scores)
    
    vec_ranked_indices = np.argsort(sim_scores_array)[::-1]
    vec_ranked_ids = [ids[i] for i in vec_ranked_indices]
    
    print(f"[RAG] 向量相似度已對所有 {len(vec_ranked_ids)} 個候選事件排序")
    print(f"[RAG] 向量相似度前5名分數: {[sim_scores_array[i] for i in vec_ranked_indices[:5]]}")
    print(f"[RAG] 向量相似度前5名ID: {vec_ranked_ids[:5]}")
    
    # RRF 融合
    # RRF 會融合所有候選事件的排名（不只是前5名）
    final_ids = reciprocal_rank_fusion([bm25_ranked_ids, vec_ranked_ids])
    
    print(f"[RAG] RRF 融合完成，已處理所有 {len(final_ids)} 個候選事件")
    print(f"[RAG] RRF 融合後前5名ID: {final_ids[:5]}")
    
    # 截取前 limit 個
    result_ids = final_ids[:limit]
    
    print(f"[RAG] AI 推薦完成，從 {len(final_ids)} 個候選事件中選出前 {len(result_ids)} 個 (limit={limit})")
    if job_id:
        _update_inference_job(job_id, status="success", progress=100.0, metrics_patch={"result_count": int(len(result_ids)), "candidates_total": int(len(candidates))})
    
    return result_ids

