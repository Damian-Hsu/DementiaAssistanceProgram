import os
from celery import Celery
from dotenv import load_dotenv
"""
celery -A services.ComputeServer.CeleryApp.app  worker -l info -Q default -P solo
"""
load_dotenv()

def _bool(env, default=False):
    v = os.getenv(env, str(default)).lower()
    return v in ("1", "true", "yes", "on")

BROKER_URL = os.getenv("BROKER_URL", "redis://redis:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
app = Celery("compute", broker=BROKER_URL, backend=RESULT_BACKEND)

# 基礎設定（從環境讀，保持與 Celery 命名一致或轉成小寫）
app.conf.update(
    task_serializer=os.getenv("CELERY_TASK_SERIALIZER", "json"),
    accept_content=[os.getenv("CELERY_ACCEPT_CONTENT", "json")],
    result_serializer=os.getenv("CELERY_RESULT_SERIALIZER", "json"),
    result_accept_content=["json"],
    result_backend=RESULT_BACKEND,
    result_expires=3600,  # 結果保留 1 小時
    task_always_eager=_bool("CELERY_TASK_ALWAYS_EAGER", False),
    task_acks_late=_bool("CELERY_ACKS_LATE", True),
    worker_prefetch_multiplier=int(os.getenv("CELERY_PREFETCH_MULTIPLIER", "1")),
    broker_transport_options={
        "visibility_timeout": int(os.getenv("CELERY_VISIBILITY_TIMEOUT", "300"))
    },
    task_time_limit=int(os.getenv("CELERY_TIME_LIMIT", "300")),
    task_soft_time_limit=int(os.getenv("CELERY_SOFT_TIME_LIMIT", "280")),
)

# 自動載入 tasks 套件
app.autodiscover_tasks(packages=["app"], related_name="tasks")

# Celery Worker 啟動時預載入模型
from celery.signals import worker_ready

@worker_ready.connect
def on_worker_ready(**kwargs):
    """
    Worker 啟動時預載入模型
    類似 BLIP 的啟動控管,確保模型在 Worker 啟動時就載入
    """
    print("[Worker] 🚀 Celery Worker 已啟動,開始預載入模型...")
    
    # 預載入 RAG Embedding 模型
    try:
        from app.libs.RAG import RAGModel
        rag = RAGModel.get_instance()
        print(f"[Worker] ✅ RAG Embedding 模型預載入完成")
    except Exception as e:
        print(f"[Worker] ⚠️ RAG 模型預載入失敗: {e}")
    
    print("[Worker] 🎯 所有模型預載入完成,Worker 準備就緒!")