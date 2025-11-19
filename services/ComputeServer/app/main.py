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
app = Celery("compute", broker=BROKER_URL)

# 基礎設定（從環境讀，保持與 Celery 命名一致或轉成小寫）
app.conf.update(
    task_serializer=os.getenv("CELERY_TASK_SERIALIZER", "json"),
    accept_content=[os.getenv("CELERY_ACCEPT_CONTENT", "json")],
    result_serializer=os.getenv("CELERY_RESULT_SERIALIZER", "json"),
    result_accept_content=["json"],
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
