# -*- coding: utf-8 -*-
import time
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import sqlite3
import requests
import boto3
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .settings import settings

# ---------- 路徑與外部服務 ----------
RECORD_ROOT = Path(settings.record_root)                 # e.g. "/recordings"
DB_PATH = Path(settings.uploader_db)                     # e.g. "/srv/app/database/uploader.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)        # 確保 DB 目錄存在

# 背景 worker thread 專用的 HTTP / S3 client
_session = requests.Session()
_s3 = boto3.client(
    "s3",
    endpoint_url=settings.minio_endpoint,
    aws_access_key_id=settings.minio_access_key,
    aws_secret_access_key=settings.minio_secret_key,
)

# ---------- SQLite outbox 初始化 ----------
con = sqlite3.connect(DB_PATH, check_same_thread=False)
con.row_factory = sqlite3.Row
con.execute("PRAGMA journal_mode=WAL;")
con.execute("PRAGMA synchronous=NORMAL;")
con.executescript("""
CREATE TABLE IF NOT EXISTS segments_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  local_path TEXT NOT NULL UNIQUE,
  s3_key TEXT NOT NULL,
  user_id TEXT NOT NULL,
  camera_id TEXT NOT NULL,
  start_time_utc TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  retry_count INTEGER NOT NULL DEFAULT 0,
  next_retry_at INTEGER,
  last_error TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_seg_status ON segments_queue(status, next_retry_at);
""")
con.commit()

def _now() -> int:
    return int(time.time())

# ---------- helpers ----------
def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _parse_path(p: Path) -> Optional[Dict[str, Any]]:
    """
    期望路徑：
      /recordings/<user_id>/<camera_id>/<Y>/<m>/<d>/<YYYYmmddTHHMMSSZ>.mp4
    """
    try:
        rel = p.relative_to(RECORD_ROOT)
        user_id, camera_id = rel.parts[0], rel.parts[1]
        y, m, d = rel.parts[2], rel.parts[3], rel.parts[4]
        fname = rel.stem  # 20250901T123000Z
        start_dt = datetime.strptime(fname, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        s3_key = f"{user_id}/videos/{camera_id}/{y}/{m}/{d}/{fname}.mp4"
        return {
            "user_id": user_id,
            "camera_id": camera_id,
            "start_iso": _utc_iso(start_dt),
            "s3_key": s3_key,
        }
    except Exception:
        return None

def _outbox_enqueue(p: Path, meta: Dict[str, Any]) -> None:
    con.execute("""
    INSERT OR IGNORE INTO segments_queue
      (local_path,s3_key,user_id,camera_id,start_time_utc,status,created_at,updated_at)
    VALUES (?,?,?,?,?,'pending',?,?)
    """, (str(p), meta["s3_key"], meta["user_id"], meta["camera_id"],
          meta["start_iso"], _now(), _now()))
    con.commit()

def _outbox_pick() -> Optional[Dict[str, Any]]:
    cur = con.execute("""
      SELECT * FROM segments_queue
      WHERE status='pending' AND (next_retry_at IS NULL OR next_retry_at<=?)
      ORDER BY created_at ASC
      LIMIT 1
    """, (_now(),))
    row = cur.fetchone()
    return dict(row) if row else None

def _outbox_mark(row_id: int, **kv) -> None:
    sets = ", ".join(f"{k}=?" for k in kv.keys())
    con.execute(f"UPDATE segments_queue SET {sets}, updated_at=? WHERE id=?",
                (*kv.values(), _now(), row_id))
    con.commit()

# ---------- 檔案入列（watchdog） ----------
def _enqueue_file(p: Path) -> None:
    if p.suffix.lower() != ".mp4":
        return
    if not p.exists():
        return
    meta = _parse_path(p)
    if not meta:
        return
    _outbox_enqueue(p, meta)

class _Handler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        _enqueue_file(Path(event.src_path))

    def on_moved(self, event):
        if event.is_directory:
            return
        _enqueue_file(Path(event.dest_path))

def _start_watchdog() -> Observer:
    observer = Observer()
    handler = _Handler()
    observer.schedule(handler, str(RECORD_ROOT), recursive=True)
    observer.daemon = True
    observer.start()
    return observer

# ---------- 核心工作：上傳 + 建 Job ----------
def _upload_and_create_job(p: Path, meta: Dict[str, Any]) -> None:
    # 1) 上傳 MinIO
    _s3.upload_file(str(p), settings.minio_bucket, meta["s3_key"])

    # 2) 通知 APIServer 建 job
    payload = {
        "type": "video_description_extraction",
        "input_type": "video",
        "input_url": f"s3://{settings.minio_bucket}/{meta['s3_key']}",
        "params": {
            "video_start_time": meta["start_iso"],
            "user_id": meta["user_id"],
            "camera_id": meta["camera_id"],
        },
    }
    headers = {"X-API-Key": settings.job_api_key, "Content-Type": "application/json"}
    r = _session.post(f"{settings.job_api_base}/jobs", json=payload, headers=headers, timeout=20)
    r.raise_for_status()

    # 3) 成功刪本地檔（避免重傳）
    try:
        p.unlink(missing_ok=True)
    except Exception:
        pass

def _worker_loop() -> None:
    while True:
        row = _outbox_pick()
        if not row:
            time.sleep(0.5)
            continue

        p = Path(row["local_path"])
        meta = {
            "s3_key": row["s3_key"],
            "user_id": row["user_id"],
            "camera_id": row["camera_id"],
            "start_iso": row["start_time_utc"],
        }

        try:
            _outbox_mark(row["id"], status="uploading", last_error=None)
            _upload_and_create_job(p, meta)
            _outbox_mark(row["id"], status="uploaded", last_error=None)
        except Exception as e:
            rc = int(row["retry_count"]) + 1
            wait = min(1800, (2 ** min(rc, 8)) * 5)  # 最長 30 分鐘
            _outbox_mark(
                row["id"],
                status="pending",
                retry_count=rc,
                next_retry_at=_now() + wait,
                last_error=str(e),
            )

def bootstrap_uploader() -> None:
    # 啟動前先掃描既有檔案，避免漏檔
    for p in RECORD_ROOT.rglob("*.mp4"):
        _enqueue_file(p)

    _start_watchdog()

    t = threading.Thread(target=_worker_loop, daemon=True)
    t.start()
