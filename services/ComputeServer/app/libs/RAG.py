import threading
import numpy as np
import jieba
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi
import torch
import os

class RAGModel:
    """
    RAG Embedding 模型單例管理器
    類似 BLIP 的啟動控管,確保模型只載入一次
    """
    _instance = None
    _lock = threading.Lock()
    _initialized = False
    
    def __init__(self):
        if RAGModel._initialized:
            return
            
        print("[RAG] 🔁 正在載入 Embedding 模型: intfloat/multilingual-e5-large ...")
        
        # 設置緩存目錄
        cache_dir = os.getenv("HF_HOME", "./adapters/.cache/huggingface")
        os.makedirs(cache_dir, exist_ok=True)
        
        # 自動檢測設備
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[RAG] 使用設備: {device}")
        
        # 載入模型
        self.model = SentenceTransformer(
            "intfloat/multilingual-e5-large",
            cache_folder=cache_dir,
            device=device
        )
        
        RAGModel._initialized = True
        print(f"[RAG] ✅ Embedding 模型已載入至 {device}")

    @classmethod
    def get_instance(cls):
        """獲取 RAG 模型單例"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    print("[RAG] 首次初始化 RAG 模型...")
                    cls._instance = cls()
        return cls._instance
    
    @classmethod
    def is_loaded(cls):
        """檢查模型是否已載入"""
        return cls._initialized
    
    def encode(self, texts: list[str], **kwargs) -> list[list[float]]:
        # E5 requires "passage: " prefix for documents and "query: " for queries.
        # We will handle prefixing outside or allow caller to specify.
        embeddings = self.model.encode(texts, normalize_embeddings=True, **kwargs)
        return embeddings

    def similarity(self, query_embeddings, chunk_embeddings):
        return self.model.similarity(query_embeddings, chunk_embeddings)

def create_bm25(chunks: list[str]) -> BM25Okapi:
    # jieba.cut returns a generator, we need list of tokens
    tokenized_chunks = [list(jieba.cut(chunk)) for chunk in chunks]
    return BM25Okapi(tokenized_chunks)

def bm25_retrieve(query: str, chunks: list[str], bm25_obj: BM25Okapi) -> list[float]:
    tokenized_query = list(jieba.cut(query))
    scores = bm25_obj.get_scores(tokenized_query)
    return scores.tolist()

def reciprocal_rank_fusion(ranked_lists: list[list[int]], k=60) -> list[int]:
    """
    ranked_lists: List of lists, where each list contains item IDs (or indices) in ranked order.
    """
    scores = {}
    for rl in ranked_lists:
        for rank, doc_id in enumerate(rl, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    
    fused = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    return [d for d, _ in fused]

