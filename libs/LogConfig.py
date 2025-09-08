# libs/log_config.py
import json
import logging
import os
import sys
from logging.handlers import WatchedFileHandler
from contextvars import ContextVar
from typing import Optional
from datetime import datetime, timezone

"""
使用範例
# services/web/app.py
from libs.log_config import setup_logging, get_logger, set_trace_id
from fastapi import FastAPI, Request
import uuid,os

setup_logging(service_name="web", file_path=os.getenv("LOG_FILE"))  # 或全靠環境變數

app = FastAPI()
log = get_logger(__name__)

@app.middleware("http")
async def add_trace_id(request: Request, call_next):
    # 1) 從 header 取或產生 trace_id
    trace = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
    set_trace_id(trace)
    try:
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace
        return response
    finally:
        set_trace_id(None)  # 清理（避免外溢到下一個請求）

#########################################
在任何地方寫 log：

from libs.log_config import get_logger
log = get_logger(__name__)
log.info("job created", extra={"job_id": "abc-123"})

#########################################
在 Celery/RQ Worker：

# services/compute/worker.py
from libs.log_config import setup_logging, get_logger, set_trace_id
setup_logging(service_name="compute", file_path=os.getenv("LOG_FILE"))

log = get_logger(__name__)

def handle_job(job_id, payload, trace_id=None):
    set_trace_id(trace_id)   # 若上游有傳 trace_id，就帶上
    try:
        log.info("job started", extra={"job_id": job_id})
        ...
    except Exception:
        log.exception("job failed", extra={"job_id": job_id})
    finally:
        set_trace_id(None)

"""

# ======== request/任務範圍的追蹤變數（可跨 async 任務） ========
_trace_id: ContextVar[Optional[str]] = ContextVar("_trace_id", default=None)

def set_trace_id(trace_id: Optional[str]) -> None:
    """在請求/任務開始時設定 trace_id；結束時可設回 None。"""
    _trace_id.set(trace_id)

def get_trace_id() -> Optional[str]:
    return _trace_id.get()

# ======== JSON 與 Text Formatter ========
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # 基本欄位
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc) \
                     .isoformat(timespec="milliseconds") \
                     .replace("+00:00", "Z")   # 讓時區顯示成 Z，代表時區為0，後面處理直接換算對應時區時間便可
        doc = {
            "ts": ts,
            "level": record.levelname.lower(),
            "svc": getattr(record, "svc", None),
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": getattr(record, "trace_id", None),
            "pid": record.process,
            "tid": record.thread,
        }
        # 例外堆疊
        if record.exc_info:
            doc["exc"] = self.formatException(record.exc_info)
        # 其餘 extra
        for k, v in record.__dict__.items():
            if k in ("args","msg","levelname","levelno","pathname","filename","module",
                     "exc_info","exc_text","stack_info","lineno","funcName","created",
                     "msecs","relativeCreated","thread","threadName","processName","process"):
                continue
            if k in doc or k in ("svc","trace_id"):
                continue
            doc[k] = v
        return json.dumps(doc, ensure_ascii=False)

class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        trace = getattr(record, "trace_id", None)
        svc = getattr(record, "svc", "-")
        base = f"[{datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')}]"
        base += f" [{record.levelname}] [{svc}] [{record.name}]"
        if trace:
            base += f" [trace={trace}]"
        base += f" - {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base

# ======== 把 svc/trace_id 注入每筆 log 的 Filter ========
class ContextFilter(logging.Filter):
    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "svc"):
            record.svc = self.service_name
        if not hasattr(record, "trace_id"):
            record.trace_id = get_trace_id()
        return True

# ======== 單例/只初始化一次的守門機制 ========
_INITIALIZED_FLAG = "_app_logging_initialized"

def _already_initialized(root: logging.Logger) -> bool:
    return getattr(root, _INITIALIZED_FLAG, False)

def _mark_initialized(root: logging.Logger) -> None:
    setattr(root, _INITIALIZED_FLAG, True)

def _has_app_handlers(root: logging.Logger) -> bool:
    return any(getattr(h, "_app_handler", False) for h in root.handlers)

# ======== 對外 API ========
def setup_logging(
    *,
    service_name: Optional[str] = None,
    level: Optional[str] = None,
    json_format: Optional[bool] = None,
    to_stdout: Optional[bool] = None,
    to_file: Optional[bool] = None,
    file_path: Optional[str] = None,
) -> None:
    """
    初始化全域 logging（重複呼叫安全、僅生效一次）

    環境變數（皆可覆寫參數）：
      SERVICE_NAME     預設 "web"
      LOG_LEVEL        預設 "INFO"（例：DEBUG/INFO/WARN/ERROR）
      LOG_JSON         "1"|"true" 啟用 JSON 格式，預設 JSON（容器建議）
      LOG_STDOUT       預設 "1"（寫 stdout）
      LOG_FILE         檔案路徑（給非容器/單機用；會用 WatchedFileHandler）
    """
    root = logging.getLogger()

    # 多模組/多處呼叫 → 直接略過
    if _already_initialized(root):
        return

    # 讀環境（參數優先，其次 env）
    service_name = service_name or os.getenv("SERVICE_NAME", "web")
    level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    json_format = json_format if json_format is not None else os.getenv("LOG_JSON", "1").lower() in ("1","true","yes")
    to_stdout = to_stdout if to_stdout is not None else os.getenv("LOG_STDOUT", "1").lower() in ("1","true","yes")
    file_path = file_path or os.getenv("LOG_FILE")
    to_file = to_file if to_file is not None else bool(file_path)

    # 設定 root level
    root.setLevel(level)

    # 避免重複加 handler（含第三方先前已設定的情形）
    # 我們只在沒有「我們的 handler」時才加
    if not _has_app_handlers(root):
        fmt = JsonFormatter() if json_format else TextFormatter()
        ctx_filter = ContextFilter(service_name=service_name)

        if to_stdout:
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(fmt)
            sh.addFilter(ctx_filter)
            sh._app_handler = True  # 打標記，避免重複掛
            root.addHandler(sh)

        if to_file and file_path:
            # 用 WatchedFileHandler：配合 logrotate 轉檔，不鎖死舊 fd
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            fh = WatchedFileHandler(file_path, encoding="utf-8")
            fh.setFormatter(fmt)
            fh.addFilter(ctx_filter)
            fh._app_handler = True
            root.addHandler(fh)

    _mark_initialized(root)

def get_logger(name: str) -> logging.Logger:
    """取得具備 svc/trace_id 欄位的 logger。"""
    return logging.getLogger(name)