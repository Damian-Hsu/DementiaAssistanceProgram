import os
from celery import Celery

BROKER_URL  = os.getenv("BROKER_URL",  "redis://redis:6379/0")
DEFAULT_Q   = os.getenv("CELERY_DEFAULT_QUEUE", "default")

# 僅作為 Producer，用同樣的 broker/backend 即可
producer = Celery("api_producer", broker=BROKER_URL)

def enqueue(task_name: str, kwargs: dict, queue: str | None = None, headers: dict | None = None):
    """
    封裝送任務。APIServer 呼叫這個函式即可。
    - task_name: 例如 "tasks.video_description_extraction"
    - kwargs:    必須是 JSON 可序列化的 dict
    - queue:     指定要投遞的 queue（預設 DEFAULT_Q）   
    - headers:   選填，自訂傳遞訊息標頭（可放 trace_id）
    """
    q = queue or DEFAULT_Q
    # 你也可以傳 reply_to/correlation_id 等 AMQP header
    return producer.send_task(task_name, kwargs=kwargs, queue=q, headers=headers or {})
