# -*- coding: utf-8 -*-
import asyncio
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta, date
from typing import Optional, Dict, Any, List, Tuple

import sqlite3
import httpx
import boto3
from botocore.exceptions import ClientError
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .settings import settings

# =========================
# 常數 / 全域狀態
# =========================
RECORD_ROOT = Path(settings.record_root)                 # e.g. "/recordings"
DB_PATH = Path(settings.uploader_db)                     # e.g. "/srv/app/database/uploader.db"

_http: Optional[httpx.AsyncClient] = None
_s3 = None  # boto3 client
_con: Optional[sqlite3.Connection] = None
_observer: Optional[Observer] = None

_FILE_QUEUE: Optional["asyncio.Queue[Path]"] = None

# =========================
# 小工具
# =========================
def _dbg(msg: str) -> None:
    # 我：把 DEBUG 交由 settings.DEBUG 控制，方便你用環境變數開關
    if getattr(settings, "DEBUG", False):
        print(f"[DEBUG] {msg}", flush=True)

def _now_i() -> int:
    return int(time.time())

def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _parse_iso_z(s: str) -> datetime:
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

def _parse_path(p: Path) -> Optional[Dict[str, Any]]:
    """
    期望路徑：
      /recordings/<user_id>/<camera_id>/<Y>/<m>/<d>/<YYYYmmddT%H%M%SZ>.mp4
    """
    try:
        rel = p.relative_to(RECORD_ROOT)
        # 我：嚴格檢查深度，避免不合規路徑入列
        if len(rel.parts) < 6:
            _dbg(f"skip (bad depth): {p}")
            return None
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
            "y": int(y), "m": int(m), "d": int(d),
        }
    except Exception as e:
        _dbg(f"skip (parse fail): {p} ({e})")
        return None

def _extract_ymd_from_path(p: Path) -> Optional[Tuple[int, int, int]]:
    """我：從路徑抽出 Y/m/d（與 _parse_path 一致的第 3~5 層），失敗回 None。"""
    try:
        rel = p.relative_to(RECORD_ROOT)
        if len(rel.parts) < 5:
            return None
        y, m, d = int(rel.parts[2]), int(rel.parts[3]), int(rel.parts[4])
        return y, m, d
    except Exception:
        return None

async def _wait_until_file_stable(
    p: Path,
    *,
    min_age_sec: float = 2.0,        # 檔案至少要「生成超過」這個秒數
    stable_for_sec: float = 5.0,     # 連續這麼久 size/mtime 都不變才算穩定
    poll_interval: float = 0.5,      # 觀察輪詢間隔
    max_wait_sec: float = 300.0      # 上限（避免卡死），到時還不穩就讓外層走重試
) -> bool:
    """
    等待檔案「穩定」：存在、可讀、且 size/mtime 在 stable_for_sec 內沒有變動。
    回傳 True=穩定；False=超時未穩定（交由外層重試策略處理）
    """
    start_ts = time.time()

    last_size = -1
    last_mtime = -1.0
    stable_start = None

    while True:
        now = time.time()
        if now - start_ts > max_wait_sec:
            return False

        if not p.exists():
            await asyncio.sleep(poll_interval)
            continue

        try:
            st = p.stat()
            size = st.st_size
            mtime = st.st_mtime
        except FileNotFoundError:
            await asyncio.sleep(poll_interval)
            continue

        # 至少要過 min_age_sec 才能判斷
        if (now - mtime) < min_age_sec:
            await asyncio.sleep(poll_interval)
            continue

        if size == last_size and mtime == last_mtime:
            if stable_start is None:
                stable_start = now
            if (now - stable_start) >= stable_for_sec:
                # 嘗試開檔讀一點點，避免單純 metadata 沒變但仍被獨占等極端狀況
                try:
                    with p.open("rb") as f:
                        f.read(1024)
                    return True
                except Exception:
                    # 無法讀取，繼續等
                    pass
        else:
            # 狀態變了，重置穩定計時
            stable_start = None
            last_size = size
            last_mtime = mtime

        await asyncio.sleep(poll_interval)

# =========================
# 檔案系統清理（安全作法）
# =========================
def _prune_empty_dirs(start_dir: Path, stop_at: Path) -> None:
    """
    我：自下而上刪除空目錄，停在 stop_at（不刪 stop_at）。
    目錄非空或越界立即停止，避免誤刪。
    """
    try:
        start_dir = start_dir.resolve()
        stop_at = stop_at.resolve()
        start_dir.relative_to(stop_at)
    except Exception:
        return

    cur = start_dir
    while True:
        if cur == stop_at:
            break
        try:
            cur.rmdir()  # 只會刪空目錄
            _dbg(f"removed empty dir: {cur}")
        except OSError:
            break
        except Exception as e:
            _dbg(f"prune empty dirs error at {cur}: {e}")
            break
        cur = cur.parent

async def _unlink_with_retries(p: Path, attempts: int = 6, delay: float = 0.25) -> bool:
    """
    我：刪檔加入重試（容器/掛載在短時間內可能 busy）。
    刪除成功或檔案不存在都回 True。
    """
    for i in range(1, attempts + 1):
        try:
            p.unlink(missing_ok=True)
            if not p.exists():
                if i > 1:
                    _dbg(f"unlink succeeded after retry #{i} -> {p}")
                return True
        except Exception as e:
            _dbg(f"unlink attempt #{i} failed for {p}: {e}")
        await asyncio.sleep(delay)
    return not p.exists()

async def _s3_object_exists(bucket: str, key: str) -> bool:
    """我：HEAD 檢查 S3 物件是否存在。"""
    def _do_head():
        try:
            assert _s3 is not None
            _s3.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError:
            return False
        except Exception:
            return False
    return await asyncio.to_thread(_do_head)

# =========================
# 遠端時鐘對齊（保留，可關閉）
# =========================
class RemoteClock:
    def __init__(self, url: Optional[str]):
        self.url = url
        self.offset_seconds: float = 0.0
        self.last_rtt: float = float("inf")
        self.enabled = bool(url)

    async def calibrate(self, http: httpx.AsyncClient, samples: int = 5, timeout: float = 3.0) -> None:
        if not self.enabled:
            return
        offsets: List[Tuple[float, float]] = []
        for _ in range(max(1, samples)):
            try:
                t_send = time.time()
                r = await http.get(self.url, timeout=timeout)
                t_recv = time.time()
                r.raise_for_status()
                data = r.json()
                server_ts = float(data.get("utc_timestamp"))
                rtt = t_recv - t_send
                offset = server_ts - (t_send + t_recv) / 2.0
                offsets.append((rtt, offset))
            except Exception as e:
                _dbg(f"RemoteClock sample error: {e}")
        if not offsets:
            _dbg("RemoteClock: no valid samples; keep previous offset")
            return
        offsets.sort(key=lambda x: x[0])
        best = offsets[: min(3, len(offsets))]
        best_offsets = [o for _, o in best]
        best_offsets.sort()
        mid = best_offsets[len(best_offsets) // 2]
        self.offset_seconds = float(mid)
        self.last_rtt = best[0][0]
        _dbg(f"RemoteClock calibrated: offset={self.offset_seconds:+.6f}s, rtt_best={self.last_rtt:.4f}s")

    def apply(self, dt_utc: datetime) -> datetime:
        if not self.enabled:
            return dt_utc
        return dt_utc + timedelta(seconds=self.offset_seconds)

# =========================
# SQLite：啟動時才開啟（新增 delete_queue）
# =========================
async def _init_sqlite() -> None:
    global _con
    RECORD_ROOT.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    def _open_and_prepare():
        con = sqlite3.connect(DB_PATH, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.executescript("""
        -- 上傳工作佇列（沿用）
        CREATE TABLE IF NOT EXISTS segments_queue (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          local_path TEXT NOT NULL UNIQUE,
          s3_key TEXT NOT NULL,
          user_id TEXT NOT NULL,
          camera_id TEXT NOT NULL,
          start_time_utc TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', -- pending/uploading/uploaded
          retry_count INTEGER NOT NULL DEFAULT 0,
          next_retry_at INTEGER,
          last_error TEXT,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_seg_status ON segments_queue(status, next_retry_at);

        -- 我新增：刪除佇列（與上傳解耦）
        CREATE TABLE IF NOT EXISTS delete_queue (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          local_path TEXT NOT NULL UNIQUE, -- 用 UNIQUE 防重
          s3_key TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', -- pending/deleting/deleted
          attempts INTEGER NOT NULL DEFAULT 0,
          last_error TEXT,
          enqueued_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_del_status ON delete_queue(status);
        """)
        con.commit()
        return con

    _con = await asyncio.to_thread(_open_and_prepare)
    _dbg(f"SQLite ready at {DB_PATH}")

# =========================
# DB helpers（segments_queue）
# =========================
async def _outbox_enqueue(p: Path, meta: Dict[str, Any]) -> None:
    def _do():
        assert _con is not None
        _con.execute("""
        INSERT OR IGNORE INTO segments_queue
          (local_path,s3_key,user_id,camera_id,start_time_utc,status,created_at,updated_at)
        VALUES (?,?,?,?,?,'pending',?,?)
        """, (str(p), meta["s3_key"], meta["user_id"], meta["camera_id"],
              meta["start_iso"], _now_i(), _now_i()))
        _con.commit()
    await asyncio.to_thread(_do)
    _dbg(f"ENQ(up) -> {p}")

async def _outbox_pick() -> Optional[Dict[str, Any]]:
    def _do():
        assert _con is not None
        cur = _con.execute("""
          SELECT * FROM segments_queue
          WHERE status='pending' AND (next_retry_at IS NULL OR next_retry_at<=?)
          ORDER BY created_at ASC
          LIMIT 1
        """, (_now_i(),))
        row = cur.fetchone()
        return dict(row) if row else None
    row = await asyncio.to_thread(_do)
    if row:
        _dbg(f"PICK(up) -> {row['local_path']} (retry={row['retry_count']})")
    return row

async def _outbox_mark(row_id: int, **kv) -> None:
    def _do():
        assert _con is not None
        sets = ", ".join(f"{k}=?" for k in kv.keys())
        _con.execute(f"UPDATE segments_queue SET {sets}, updated_at=? WHERE id=?",
                     (*kv.values(), _now_i(), row_id))
        _con.commit()
    await asyncio.to_thread(_do)

# =========================
# DB helpers（delete_queue）
# =========================
async def _delq_enqueue(local_path: Path, s3_key: str) -> None:
    """我：上傳 + 建 Job 成功後，把本地檔放入刪除佇列（與刪除工作解耦）。"""
    def _do():
        assert _con is not None
        _con.execute("""
        INSERT OR IGNORE INTO delete_queue (local_path, s3_key, status, enqueued_at, updated_at)
        VALUES (?, ?, 'pending', ?, ?)
        """, (str(local_path), s3_key, _now_i(), _now_i()))
        _con.commit()
    await asyncio.to_thread(_do)
    _dbg(f"ENQ(del) -> {local_path}")

async def _delq_pick() -> Optional[Dict[str, Any]]:
    """我：挑一筆刪除工作（pending）。"""
    def _do():
        assert _con is not None
        cur = _con.execute("""
        SELECT * FROM delete_queue
        WHERE status='pending'
        ORDER BY enqueued_at ASC
        LIMIT 1
        """)
        row = cur.fetchone()
        return dict(row) if row else None
    row = await asyncio.to_thread(_do)
    if row:
        _dbg(f"PICK(del) -> {row['local_path']} (attempts={row['attempts']})")
    return row

async def _delq_mark(row_id: int, **kv) -> None:
    def _do():
        assert _con is not None
        sets = ", ".join(f"{k}=?" for k in kv.keys())
        _con.execute(f"UPDATE delete_queue SET {sets}, updated_at=? WHERE id=?",
                     (*kv.values(), _now_i(), row_id))
        _con.commit()
    await asyncio.to_thread(_do)

# =========================
# watchdog -> asyncio.Queue
# =========================
class _Handler(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop, q: "asyncio.Queue[Path]"):
        self.loop = loop
        self.q = q

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.lower().endswith(".mp4"):
            self.loop.call_soon_threadsafe(self.q.put_nowait, Path(event.src_path))

    def on_moved(self, event):
        if event.is_directory:
            return
        if event.dest_path.lower().endswith(".mp4"):
            self.loop.call_soon_threadsafe(self.q.put_nowait, Path(event.dest_path))

def _start_watchdog(loop: asyncio.AbstractEventLoop, q: "asyncio.Queue[Path]", root: Path) -> Observer:
    observer = Observer()
    handler = _Handler(loop, q)
    observer.schedule(handler, str(root), recursive=True)
    observer.daemon = True
    observer.start()
    _dbg(f"watchdog started on {root}")
    return observer

# =========================
# 上傳 + 建 Job（不直接刪檔，改入刪除佇列）
# =========================
async def _upload_and_create_job(p: Path, meta: Dict[str, Any], rclock: RemoteClock) -> None:
    assert _http is not None and _s3 is not None

    # 0) 關鍵：確保檔案穩定（否則讓外層重試退避）
    ok = await _wait_until_file_stable(
        p,
        min_age_sec=2.0,
        stable_for_sec=5.0,
        poll_interval=0.5,
        max_wait_sec=300.0
    )
    if not ok:
        raise RuntimeError(f"file not stable yet: {p}")

    # 1) S3 上傳
    await asyncio.to_thread(_s3.upload_file, str(p), settings.minio_bucket, meta["s3_key"])
    _dbg(f"S3 PUT ok -> s3://{settings.minio_bucket}/{meta['s3_key']}")

    # 2) HEAD 確認存在（我保守：上傳後立即確認）
    exists = await _s3_object_exists(settings.minio_bucket, meta["s3_key"])
    if not exists:
        raise RuntimeError(f"S3 object not visible yet: s3://{settings.minio_bucket}/{meta['s3_key']}")

    # 3) 時間對齊 → 建 Job
    start_dt_local = _parse_iso_z(meta["start_iso"])
    start_dt_api   = rclock.apply(start_dt_local)
    start_iso_api  = _utc_iso(start_dt_api)

    payload = {
        "type": "video_description_extraction",
        "input_type": "video",
        "input_url": f"s3://{settings.minio_bucket}/{meta['s3_key']}",
        "params": {
            "video_start_time": start_iso_api,
            "user_id": meta["user_id"],
            "camera_id": meta["camera_id"],
        },
    }
    headers = {"X-API-Key": settings.job_api_key, "Content-Type": "application/json"}
    resp = await _http.post(f"{settings.job_api_base}/jobs", json=payload, headers=headers)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        _dbg(f"API ERROR body: {e.response.text if e.response else ''}")
        raise
    _dbg(f"API /jobs ok -> {p.name}")

    # 4) 我改：不在這裡刪檔，改丟進 delete_queue，由獨立 worker 處理
    await _delq_enqueue(p, meta["s3_key"])

# =========================
# 生產者：啟動掃描 + 事件入列 + 週期 rescanner
# =========================
async def _producer_scan_existing(q: "asyncio.Queue[Path]"):
    cnt = 0
    for p in RECORD_ROOT.rglob("*.mp4"):
        await q.put(p)
        cnt += 1
    _dbg(f"initial scan queued {cnt} files")

async def _producer_enqueue_loop(q: "asyncio.Queue[Path]", stop: asyncio.Event):
    while not stop.is_set():
        try:
            p = await asyncio.wait_for(q.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        meta = _parse_path(p)
        if meta:
            await _outbox_enqueue(p, meta)

# 我：保險機制（漏事件也能補上）
async def _periodic_rescan(stop: asyncio.Event, interval_sec: int = 60):
    while not stop.is_set():
        try:
            added = 0
            for p in RECORD_ROOT.rglob("*.mp4"):
                meta = _parse_path(p)
                if meta:
                    await _outbox_enqueue(p, meta)
                    added += 1
            _dbg(f"rescan added (dedup by DB) ~{added} candidates")
        except Exception as e:
            _dbg(f"rescan error: {e}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_sec)
        except asyncio.TimeoutError:
            pass

# =========================
# 消費者：上傳
# =========================
async def _consumer_worker(stop: asyncio.Event, rclock: RemoteClock):
    backoff_idle = 0.5
    while not stop.is_set():
        row = await _outbox_pick()
        if not row:
            await asyncio.sleep(backoff_idle)
            continue

        p = Path(row["local_path"])
        meta = {
            "s3_key": row["s3_key"],
            "user_id": row["user_id"],
            "camera_id": row["camera_id"],
            "start_iso": row["start_time_utc"],
        }

        try:
            await _outbox_mark(row["id"], status="uploading", last_error=None)
            await _upload_and_create_job(p, meta, rclock)
            await _outbox_mark(row["id"], status="uploaded", last_error=None)
            _dbg(f"DONE(up) -> {p}")
        except Exception as e:
            rc = int(row["retry_count"]) + 1
            wait = min(1800, (2 ** min(rc, 8)) * 5)
            await _outbox_mark(
                row["id"],
                status="pending",
                retry_count=rc,
                next_retry_at=_now_i() + wait,
                last_error=str(e),
            )
            _dbg(f"upload error: {e}; will retry in {wait}s")

# =========================
# 消費者：刪除（新）
# =========================
async def _deleter_worker(stop: asyncio.Event):
    """
    我：專責刪除本地檔。流程：
      - 取一筆 delete_queue(pending)
      - 再 HEAD 一次 S3（保守）
      - 刪除本地檔（含重試）
      - 若檔案位於「非今日」的日期資料夾，才嘗試向上 prune 空目錄
      - 成功：status=deleted；失敗：status 留 pending 並 attempts++、last_error 記錄
    """
    while not stop.is_set():
        row = await _delq_pick()
        if not row:
            await asyncio.sleep(0.5)
            continue

        row_id = row["id"]
        local_path = Path(row["local_path"])
        s3_key = row["s3_key"]

        try:
            # 標記 deleting
            await _delq_mark(row_id, status="deleting")

            # 1) 再確認 S3 存在（防止極端邊緣）
            exists = await _s3_object_exists(settings.minio_bucket, s3_key)
            if not exists:
                raise RuntimeError(f"S3 object missing on delete phase: s3://{settings.minio_bucket}/{s3_key}")

            # 2) 刪檔（成功或不存在皆視為 OK）
            ok = await _unlink_with_retries(local_path, attempts=6, delay=0.25)
            if not ok:
                raise RuntimeError("unlink failed after retries")

            # 3) 不是今日的日期資料夾，才做往上清理空目錄（避免「不停新建又刪除」）
            ymd = _extract_ymd_from_path(local_path)
            today = datetime.now(timezone.utc).date()
            if ymd is not None:
                y, m, d = ymd
                if date(y, m, d) != today:
                    _prune_empty_dirs(local_path.parent, RECORD_ROOT)

            # 4) 成功
            await _delq_mark(row_id, status="deleted", last_error=None)
            _dbg(f"DONE(del) -> {local_path}")

        except Exception as e:
            # 回到 pending，計數 +1，錯誤保留，稍後再試
            attempts = int(row.get("attempts", 0)) + 1
            await _delq_mark(row_id, status="pending", attempts=attempts, last_error=str(e))
            _dbg(f"delete error: {e}; will retry later")

# =========================
# 週期性校時（保留）
# =========================
async def _clock_maintainer(stop: asyncio.Event, rclock: RemoteClock):
    if not rclock.enabled:
        return
    try:
        assert _http is not None
        await rclock.calibrate(_http, samples=5)
    except Exception as e:
        _dbg(f"clock initial calibrate failed: {e}")

    while not stop.is_set():
        try:
            assert _http is not None
            await rclock.calibrate(_http, samples=3)
        except Exception as e:
            _dbg(f"clock re-calibrate failed: {e}")
        try:
            await asyncio.wait_for(stop.wait(), timeout=300)
        except asyncio.TimeoutError:
            pass

# =========================
# 啟停介面
# =========================
async def _startup_checks():
    # 我：啟動時做一些不阻斷的檢查，幫你快速定位設定問題
    try:
        assert _s3 is not None
        await asyncio.to_thread(_s3.head_bucket, Bucket=settings.minio_bucket)
        _dbg(f"MinIO bucket ok: {settings.minio_bucket}")
    except Exception as e:
        _dbg(f"MinIO bucket check failed: {e}")

    try:
        assert _http is not None
        r = await _http.get(f"{settings.job_api_base}/healthz", timeout=5)
        _dbg(f"API healthz: {r.status_code}")
    except Exception as e:
        _dbg(f"API healthz check failed: {e}")

    if not getattr(settings, "job_api_key", None):
        _dbg("WARNING: settings.job_api_key is empty; /jobs will 401")

async def start_uploader_async(stop_event: asyncio.Event) -> List[asyncio.Task]:
    global _http, _s3, _observer, _FILE_QUEUE

    await _init_sqlite()

    _http = httpx.AsyncClient(timeout=20)
    _s3 = boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )

    # 我：若沒設定 clock_api_url 就關閉校時（避免不必要的錯誤訊息）
    clock_url = getattr(settings, "clock_api_url", None) or None
    rclock = RemoteClock(clock_url)

    loop = asyncio.get_running_loop()
    _FILE_QUEUE = asyncio.Queue(maxsize=1000)
    _observer = _start_watchdog(loop, _FILE_QUEUE, RECORD_ROOT)

    async def _watchdog_guard():
        try:
            await stop_event.wait()
        finally:
            if _observer:
                try:
                    _observer.stop()
                    _observer.join(timeout=3)
                except Exception:
                    pass

    # 啟動前做檢查
    await _startup_checks()

    tasks = [
        asyncio.create_task(_watchdog_guard(), name="uploader-watchdog-guard"),
        asyncio.create_task(_producer_scan_existing(_FILE_QUEUE), name="uploader-scan"),
        asyncio.create_task(_producer_enqueue_loop(_FILE_QUEUE, stop_event), name="uploader-enqueue"),
        asyncio.create_task(_consumer_worker(stop_event, rclock), name="uploader-consumer"),
        asyncio.create_task(_clock_maintainer(stop_event, rclock), name="uploader-clock"),
        asyncio.create_task(_periodic_rescan(stop_event, 60), name="uploader-rescan"),
        # 我：新增的刪除 worker
        asyncio.create_task(_deleter_worker(stop_event), name="uploader-deleter"),
    ]
    _dbg("uploader tasks started")
    return tasks

async def shutdown_uploader_async(tasks: List[asyncio.Task]) -> None:
    global _http, _con
    try:
        if _http:
            await _http.aclose()
    except Exception:
        pass

    for t in tasks:
        try:
            await asyncio.wait_for(t, timeout=3)
        except asyncio.TimeoutError:
            t.cancel()

    try:
        if _con:
            await asyncio.to_thread(_con.close)
    except Exception:
        pass

    _dbg("uploader shutdown complete")
