"""
Vlog 生成任務
處理視頻剪輯、合併、轉碼等操作
"""
import os
import logging
import gc
from typing import List, Dict, Any, Tuple, Callable
from datetime import datetime, timezone
from celery import Task
from ..main import app
import tempfile
import subprocess
import requests
import shutil

# 設置日誌
logger = logging.getLogger(__name__)

# API 配置
API_BASE_URL = os.getenv('JOB_API_BASE', 'http://api:30000/api/v1')
API_HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": os.getenv("JOB_API_KEY", "")
}

# MinIO 配置
_raw_minio_endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")
if "://" in _raw_minio_endpoint:
    _scheme, _endpoint = _raw_minio_endpoint.split("://", 1)
    MINIO_ENDPOINT = _endpoint
    MINIO_SECURE = _scheme.lower() == "https"
else:
    MINIO_ENDPOINT = _raw_minio_endpoint
    MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "media-bucket")

# 片段處理參數
SEGMENT_PADDING_SECONDS = float(os.getenv("VLOG_SEGMENT_PADDING_SECONDS", "1"))
DEFAULT_SEGMENT_DURATION = float(os.getenv("VLOG_DEFAULT_SEGMENT_DURATION", "5"))
MAX_SEGMENT_DURATION = float(os.getenv("VLOG_MAX_SEGMENT_DURATION", "6"))  # 每個事件最多6秒
MIN_SEGMENT_DURATION = float(os.getenv("VLOG_MIN_SEGMENT_DURATION", "1"))
MERGE_GAP_THRESHOLD = float(os.getenv("VLOG_MERGE_GAP_THRESHOLD", "0.3"))  # 合併間隔閾值（秒）


def _update_vlog_status(
    vlog_id: str,
    status: str | None = None,
    *,
    s3_key: str | None = None,
    thumbnail_s3_key: str | None = None,
    duration: float | None = None,
    progress: float | None = None,
    status_message: str | None = None,
    error_message: str | None = None,
):
    """調用 API 更新 Vlog 狀態"""
    url = f"{API_BASE_URL}/vlogs/internal/{vlog_id}/status"
    payload: Dict[str, Any] = {}
    if status:
        payload["status"] = status
    if s3_key:
        payload["s3_key"] = s3_key
    if thumbnail_s3_key:
        payload["thumbnail_s3_key"] = thumbnail_s3_key
    if duration is not None:
        payload["duration"] = duration
    if progress is not None:
        payload["progress"] = max(0.0, min(100.0, float(progress)))
    if status_message is not None:
        payload["status_message"] = status_message
    if error_message is not None:
        payload["error_message"] = error_message

    if not payload:
        return

    try:
        response = requests.patch(url, json=payload, headers=API_HEADERS, timeout=10)
        response.raise_for_status()
        logger.info(f"Vlog {vlog_id} 狀態更新: {payload}")
    except Exception as e:
        logger.error(f"更新 Vlog 狀態失敗: {e}")


def _get_video_segments(event_ids: List[str]) -> List[Dict[str, Any]]:
    """調用 API 獲取視頻片段信息"""
    if not event_ids:
        return []
        
    url = f"{API_BASE_URL}/vlogs/internal/segments"
    payload = {"event_ids": event_ids}
    
    try:
        response = requests.post(url, json=payload, headers=API_HEADERS, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"獲取視頻片段信息失敗: {e}")
        raise


def _parse_s3_path(raw: str) -> Tuple[str, str]:
    """解析 s3://bucket/object or bucket/object or object"""
    if not raw:
        raise ValueError("缺少 s3_key")

    if raw.startswith("s3://"):
        without_scheme = raw[5:]
        parts = without_scheme.split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        return bucket, key

    parts = raw.split("/", 1)
    if len(parts) == 1:
        return MINIO_BUCKET, parts[0]

    return parts[0], parts[1]


def _merge_event_ranges(segments: List[Dict[str, Any]], merge_gap: float = 0.3) -> List[Dict[str, Any]]:
    """
    合併重疊或相鄰的事件區間（Union of intervals）
    
    規則：
    1. 按 start_offset 排序
    2. 若兩事件重疊（下一段 start ≤ 上一段 end）→ 合併
    3. 若兩事件間隔 ≤ merge_gap → 也合併（避免硬切）
    
    Args:
        segments: 事件片段列表，每個包含 start_offset, duration, recording_duration
        merge_gap: 合併間隔閾值（秒），預設 0.3 秒
    
    Returns:
        合併後的不重疊區間列表
    """
    if not segments:
        return []
    
    # 按 start_offset 排序
    sorted_segments = sorted(segments, key=lambda s: s["start_offset"])
    
    merged_ranges: List[Dict[str, Any]] = []
    
    for seg in sorted_segments:
        start = seg["start_offset"]
        end = start + seg["duration"]
        recording_duration = seg.get("recording_duration", 0.0)
        
        # 限制在錄影長度內
        if recording_duration > 0:
            end = min(end, recording_duration)
        
        if not merged_ranges:
            # 第一個區間
            merged_ranges.append({
                "start": start,
                "end": end,
                "recording_duration": recording_duration,
                "bucket": seg.get("bucket"),
                "object_name": seg.get("object_name"),
                "recording_id": seg.get("recording_id"),
                "event_ids": [seg.get("event_id")],  # 記錄包含的事件 ID
                "min_order": seg.get("order", 999999),  # 記錄最小的事件順序（用於排序）
            })
        else:
            # 檢查是否與最後一個區間重疊或接近
            last_range = merged_ranges[-1]
            last_end = last_range["end"]
            
            # 檢查是否重疊（start <= last_end）或間隔很小（start - last_end <= merge_gap）
            if start <= last_end or (start - last_end) <= merge_gap:
                # 合併：擴展最後一個區間的 end
                last_range["end"] = max(last_end, end)
                # 記錄包含的事件 ID
                if seg.get("event_id"):
                    last_range["event_ids"].append(seg.get("event_id"))
                # 更新最小順序（取更小的 order）
                current_order = seg.get("order", 999999)
                if current_order < last_range.get("min_order", 999999):
                    last_range["min_order"] = current_order
            else:
                # 不重疊，新增一個區間
                merged_ranges.append({
                    "start": start,
                    "end": end,
                    "recording_duration": recording_duration,
                    "bucket": seg.get("bucket"),
                    "object_name": seg.get("object_name"),
                    "recording_id": seg.get("recording_id"),
                    "event_ids": [seg.get("event_id")],
                    "min_order": seg.get("order", 999999),  # 記錄最小的事件順序（用於排序）
                })
    
    logger.info(f"[Vlog] 事件區間合併: {len(segments)} 個事件 → {len(merged_ranges)} 個不重疊區間")
    for i, r in enumerate(merged_ranges):
        logger.info(f"[Vlog]   區間 {i+1}: [{r['start']:.2f}, {r['end']:.2f}] (時長: {r['end']-r['start']:.2f}秒, 事件: {len(r['event_ids'])} 個)")
    
    return merged_ranges

def _merge_clipped_segments(prepared: List[Dict[str, Any]], merge_gap: float = 0.0) -> List[Dict[str, Any]]:
    """
    對同一支影片 (同 bucket/object_name/recording_id) 的 clip 做區間合併，
    規則：
      - 有重疊或間隔 <= merge_gap 的 clip → 合併成一段
      - 合併後如果少掉的時間 (lost_time) > 0，就優先向前擴張 start 來補回
      - 向前擴展失敗則向後擴展
    
    Args:
        prepared: Stage 3 產出的片段列表，每個包含 clip_start, clip_duration, bucket, object_name, recording_id 等
        merge_gap: 合併間隔閾值（秒），預設 0.0（只合併重疊的）
    
    Returns:
        合併後的片段列表
    """
    from collections import defaultdict
    
    # 按 (bucket, object_name, recording_id) 分組
    groups = defaultdict(list)
    for seg in prepared:
        key = (seg.get("bucket"), seg.get("object_name"), seg.get("recording_id"))
        groups[key].append(seg)
    
    merged_all: List[Dict[str, Any]] = []
    
    for key, segs in groups.items():
        bucket, object_name, recording_id = key
        
        # 只有一個片段，直接添加
        if len(segs) == 1:
            merged_all.append(segs[0])
            continue
        
        # 先依 clip_start 排序
        segs_sorted = sorted(segs, key=lambda s: s.get("clip_start", 0))
        
        merged: List[Dict[str, Any]] = []
        recording_duration = segs_sorted[0].get("recording_duration", 0.0)
        
        for seg in segs_sorted:
            start = seg.get("clip_start", 0.0)
            duration = seg.get("clip_duration", 0.0)
            end = start + duration
            
            if not merged:
                # 第一個直接放進去
                seg["_end"] = end  # 暫存方便計算
                merged.append(seg)
                continue
            
            last = merged[-1]
            last_start = last.get("clip_start", 0.0)
            last_duration = last.get("clip_duration", 0.0)
            last_end = last.get("_end", last_start + last_duration)
            
            # 是否重疊或間隔很小
            if start <= last_end + merge_gap:
                # 合併這兩段：只做 union，不補 lost_time（避免製造新重疊）
                merged_start = last_start
                merged_end = max(last_end, end)
                merged_len = merged_end - merged_start
                
                last["clip_start"] = merged_start
                last["clip_duration"] = merged_len
                last["_end"] = merged_end
                logger.info(f"[Vlog] Clip 合併：Recording {recording_id} 合併重疊 clip [{last_start:.2f}, {last_end:.2f}] 和 [{start:.2f}, {end:.2f}] → [{merged_start:.2f}, {merged_end:.2f}]")
                
                # 合併後可能往左補到前一段 → 需要回頭再合一次
                while len(merged) >= 2:
                    prev = merged[-2]
                    prev_start = prev.get("clip_start", 0.0)
                    prev_end = prev.get("_end", prev_start + prev.get("clip_duration", 0.0))
                    
                    if last["clip_start"] <= prev_end + merge_gap:
                        # 再合 prev 和 last
                        new_start = prev_start
                        new_end = max(prev_end, last["_end"])
                        new_len = new_end - new_start
                        
                        prev["clip_start"] = new_start
                        prev["clip_duration"] = new_len
                        prev["_end"] = new_end
                        
                        # 合併 meta
                        if "event_ids" in last:
                            if "event_ids" not in prev:
                                prev["event_ids"] = [prev.get("event_id")]
                            prev["event_ids"].extend(last.get("event_ids", [last.get("event_id")]))
                        else:
                            if "event_ids" not in prev:
                                prev["event_ids"] = [prev.get("event_id")]
                            prev["event_ids"].append(last.get("event_id"))
                        
                        # 更新 range 信息
                        if "range_start" in last and "range_start" in prev:
                            prev["range_start"] = min(prev.get("range_start", 0), last.get("range_start", 0))
                        if "range_end" in last and "range_end" in prev:
                            prev["range_end"] = max(prev.get("range_end", 0), last.get("range_end", 0))
                            prev["range_len"] = prev["range_end"] - prev["range_start"]
                        
                        # 更新 is_expanded 標記
                        if last.get("is_expanded", False) or prev.get("is_expanded", False):
                            prev["is_expanded"] = True
                        
                        merged.pop()  # last 被吃掉
                        last = prev
                        logger.info(f"[Vlog] Clip 合併：Recording {recording_id} 回頭合併，結果 [{new_start:.2f}, {new_end:.2f}]")
                    else:
                        break
                
                # 合併 meta（如果沒有在 while 循環中處理）
                if "event_ids" in seg:
                    if "event_ids" not in last:
                        last["event_ids"] = [last.get("event_id")]
                    last["event_ids"].extend(seg.get("event_ids", [seg.get("event_id")]))
                else:
                    if "event_ids" not in last:
                        last["event_ids"] = [last.get("event_id")]
                    last["event_ids"].append(seg.get("event_id"))
                
                # 更新 range 信息（使用合併後的範圍）
                if "range_start" in seg and "range_start" in last:
                    last["range_start"] = min(last.get("range_start", 0), seg.get("range_start", 0))
                if "range_end" in seg and "range_end" in last:
                    last["range_end"] = max(last.get("range_end", 0), seg.get("range_end", 0))
                    last["range_len"] = last["range_end"] - last["range_start"]
                
                # 更新 is_expanded 標記
                if seg.get("is_expanded", False) or last.get("is_expanded", False):
                    last["is_expanded"] = True
            else:
                # 不重疊，新增一個片段
                seg["_end"] = end
                merged.append(seg)
        
        # 清掉暫存欄位
        for m in merged:
            m.pop("_end", None)
        
        merged_all.extend(merged)
        
        if len(segs) > len(merged):
            logger.info(f"[Vlog] Clip 合併：Recording {recording_id} 將 {len(segs)} 個 clip 合併為 {len(merged)} 個")
    
    return merged_all

def _final_no_overlap_guard(prepared: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    最終的 no-overlap guard：強制保證同一支影片內的片段絕對不重疊
    如果發現重疊，會 trim 後面的片段頭部，確保不重疊
    
    Args:
        prepared: Stage 4 產出的片段列表
    
    Returns:
        保證不重疊的片段列表
    """
    from collections import defaultdict
    
    groups = defaultdict(list)
    for p in prepared:
        key = (p.get("bucket"), p.get("object_name"), p.get("recording_id"))
        groups[key].append(p)
    
    fixed = []
    
    for key, segs in groups.items():
        bucket, object_name, recording_id = key
        
        # 按 clip_start 排序
        segs = sorted(segs, key=lambda s: s.get("clip_start", 0))
        
        prev_end = None
        for s in segs:
            start = s.get("clip_start", 0.0)
            duration = s.get("clip_duration", 0.0)
            end = start + duration
            
            if prev_end is not None and start < prev_end:
                # 發現重疊，trim 頭部
                trim = prev_end - start
                new_start = prev_end
                new_dur = max(0.0, duration - trim)
                
                if new_dur < MIN_SEGMENT_DURATION * 0.5:
                    # 太短就丟掉
                    logger.warning(f"[Vlog] No-overlap guard: Recording {recording_id} 片段 [{start:.2f}, {end:.2f}] 因重疊被 trim 後太短({new_dur:.2f}秒 < {MIN_SEGMENT_DURATION * 0.5:.2f}秒)，已丟棄")
                    continue
                
                s["clip_start"] = new_start
                s["clip_duration"] = new_dur
                logger.info(f"[Vlog] No-overlap guard: Recording {recording_id} 片段 [{start:.2f}, {end:.2f}] 因重疊被 trim 至 [{new_start:.2f}, {new_start + new_dur:.2f}]")
                end = new_start + new_dur
            
            prev_end = end
            fixed.append(s)
    
    return fixed

def _prepare_segments(event_ids: List[str], raw_segments: List[Dict[str, Any]], max_duration: float = 180.0) -> List[Dict[str, Any]]:
    """
    按照事件順序準備剪輯片段，使用三段式壓縮（Feasible Cap → Global Scale → Center Clip）
    
    規則：
    - Stage 1 (Feasible Cap): 對每個事件計算可行上限（考慮 range 長度和 MAX），不先抬 MIN
    - Stage 2 (Global Scale + Min Lock): 全局等比縮放，然後鎖定 min，剩餘時間再分配
    - Stage 3 (Center Clip): 以事件中點為中心剪輯，強制夾在 range 內，不允許超出
    
    名詞定義：
    - range_i: 事件區間 [start_offset_i, start_offset_i + duration_i]
    - range_len_i: 事件區間長度 duration_i
    - MAX: MAX_SEGMENT_DURATION (最大長度)
    - MIN: MIN_SEGMENT_DURATION (最小長度)
    - max_total: max_duration (最大總時長)
    
    Args:
        event_ids: 事件 ID 列表
        raw_segments: 原始片段資訊
        max_duration: 最大總時長（秒）
    
    Returns:
        準備好的片段列表
    """
    # 名詞統一
    MAX = MAX_SEGMENT_DURATION
    MIN = MIN_SEGMENT_DURATION
    max_total = max_duration
    
    segment_map = {str(seg.get("event_id")): seg for seg in raw_segments}
    raw_valid_segments: List[Dict[str, Any]] = []

    # 第一步：收集所有有效的事件片段資訊
    for idx, eid in enumerate(event_ids):
        seg = segment_map.get(str(eid))
        if not seg:
            logger.warning(f"[Vlog] 找不到事件 {eid} 的錄影資訊，已跳過")
            continue

        try:
            bucket, object_name = _parse_s3_path(seg.get("s3_key", ""))
        except ValueError as exc:
            logger.error(f"[Vlog] 無法解析事件 {eid} 的 s3_key: {exc}")
            continue

        start_offset = float(seg.get("start_offset") or 0.0)
        duration = float(seg.get("duration") or 0.0)
        recording_duration = float(seg.get("recording_duration") or 0.0)

        if duration <= 0:
            duration = DEFAULT_SEGMENT_DURATION

        if recording_duration <= 0:
            logger.warning(f"[Vlog] 事件 {eid} 的錄影長度無效，已跳過")
            continue

        # 獲取 recording_id（如果有的話）
        recording_id = str(seg.get("recording_id", "")) if seg.get("recording_id") else None
        
        # 計算事件區間的實際範圍
        range_start = start_offset
        range_end = start_offset + duration
        range_len = duration
        
        raw_valid_segments.append({
            "event_id": str(eid),
            "order": idx,  # 原始事件順序（按時間排序）
            "bucket": bucket,
            "object_name": object_name,
            "recording_id": recording_id,
            "range_start": range_start,
            "range_end": range_end,
            "range_len": range_len,
            "recording_duration": recording_duration,
        })
    
    # 第二步：按 recording_id 分組，合併同一個 recording 內重疊的 range
    from collections import defaultdict
    recording_groups = defaultdict(list)
    
    for seg in raw_valid_segments:
        recording_id = seg.get("recording_id") or "unknown"
        recording_groups[recording_id].append(seg)
    
    valid_segments: List[Dict[str, Any]] = []
    
    for recording_id, segs in recording_groups.items():
        if len(segs) == 1:
            # 只有一個事件，直接使用
            valid_segments.append(segs[0])
        else:
            # 多個事件，需要合併重疊的 range
            # 按 range_start 排序
            sorted_segs = sorted(segs, key=lambda s: s["range_start"])
            
            merged_ranges = []
            for seg in sorted_segs:
                range_start = seg["range_start"]
                range_end = seg["range_end"]
                recording_duration = seg["recording_duration"]
                
                if not merged_ranges:
                    # 第一個區間
                    merged_ranges.append({
                        "range_start": range_start,
                        "range_end": range_end,
                        "event_ids": [seg["event_id"]],
                        "min_order": seg["order"],
                        "recording_duration": recording_duration,
                        "bucket": seg["bucket"],
                        "object_name": seg["object_name"],
                        "recording_id": seg["recording_id"],
                    })
                else:
                    # 檢查是否與最後一個區間重疊
                    last_range = merged_ranges[-1]
                    last_start = last_range["range_start"]
                    last_end = last_range["range_end"]
                    
                    # 使用 MERGE_GAP_THRESHOLD 來合併相近的事件
                    if range_start <= last_end + MERGE_GAP_THRESHOLD:
                        # 重疊：合併區間
                        # 計算重疊的長度
                        overlap = last_end - range_start
                        
                        # 計算合併前的總長度
                        original_total_length = (last_end - last_start) + (range_end - range_start)
                        
                        # 合併後的區間（簡單合併）
                        merged_start = last_start
                        merged_end = max(last_end, range_end)
                        merged_length = merged_end - merged_start
                        
                        # 計算損失的時間（重疊部分）
                        lost_time = original_total_length - merged_length
                        
                        # 嘗試向前（向左）擴展，補回損失的時間
                        new_start = max(0, merged_start - lost_time)
                        new_end = merged_end
                        
                        # 檢查向前擴展是否成功（沒有超出影片範圍）
                        if new_start >= 0:
                            # 向前擴展成功
                            last_range["range_start"] = new_start
                            last_range["range_end"] = new_end
                            logger.info(f"[Vlog] Recording {recording_id}: 合併重疊區間 [{last_start:.2f}, {last_end:.2f}] 和 [{range_start:.2f}, {range_end:.2f}]，重疊 {overlap:.2f}秒，損失 {lost_time:.2f}秒，向前擴展至 [{new_start:.2f}, {new_end:.2f}]")
                        else:
                            # 向前擴展失敗（超出左邊界），嘗試向後（向右）擴展
                            new_start = merged_start
                            new_end = min(recording_duration, merged_end + lost_time)
                            last_range["range_start"] = new_start
                            last_range["range_end"] = new_end
                            logger.info(f"[Vlog] Recording {recording_id}: 合併重疊區間 [{last_start:.2f}, {last_end:.2f}] 和 [{range_start:.2f}, {range_end:.2f}]，重疊 {overlap:.2f}秒，損失 {lost_time:.2f}秒，向前擴展失敗，向後擴展至 [{new_start:.2f}, {new_end:.2f}]")
                        
                        last_range["event_ids"].append(seg["event_id"])
                        last_range["min_order"] = min(last_range["min_order"], seg["order"])
                    else:
                        # 不重疊，新增一個區間
                        merged_ranges.append({
                            "range_start": range_start,
                            "range_end": range_end,
                            "event_ids": [seg["event_id"]],
                            "min_order": seg["order"],
                            "recording_duration": recording_duration,
                            "bucket": seg["bucket"],
                            "object_name": seg["object_name"],
                            "recording_id": seg["recording_id"],
                        })
            
            # 將合併後的區間轉換為 valid_segments 格式
            for merged in merged_ranges:
                range_len = merged["range_end"] - merged["range_start"]
                # 使用第一個 event_id 作為主要標識（但保留所有 event_ids 信息）
                valid_segments.append({
                    "event_id": merged["event_ids"][0],  # 使用第一個事件 ID
                    "event_ids": merged["event_ids"],  # 保留所有事件 ID
                    "order": merged["min_order"],
                    "bucket": merged["bucket"],
                    "object_name": merged["object_name"],
                    "recording_id": merged["recording_id"],
                    "range_start": merged["range_start"],
                    "range_end": merged["range_end"],
                    "range_len": range_len,
                    "recording_duration": merged["recording_duration"],
                })
            
            logger.info(f"[Vlog] Recording {recording_id}: 合併了 {len(segs)} 個事件 → {len(merged_ranges)} 個區間")
            for i, merged in enumerate(merged_ranges):
                logger.info(f"[Vlog]   區間 {i+1}: [{merged['range_start']:.2f}, {merged['range_end']:.2f}] (時長: {merged['range_end']-merged['range_start']:.2f}秒, 事件: {len(merged['event_ids'])} 個)")
    
    # 合併後，按原始事件順序排序（使用 min_order）
    valid_segments.sort(key=lambda s: s.get("order", 999999))

    # 檢查有效事件數
    N = len(valid_segments)
    if N < 1:
        logger.error(f"[Vlog] 有效事件數不足，無法生成 Vlog")
        return []
    
    logger.info(f"[Vlog] 有效事件數: {N}，最大總時長: {max_total:.2f}秒")
    
    # ==========================================
    # Stage 1 — Baseline 平均分配 + 可行上限 cap
    # ==========================================
    # 1. 計算 baseline 平均長度（直接使用平均，不含 padding）
    L = max_total / N if N > 0 else 0.0
    
    # 2. 每段先算可行總長上限
    feasible_total: List[float] = []
    base_total: List[float] = []  # 基準總長度
    
    for seg in valid_segments:
        range_len_i = seg["range_len"]
        recording_duration_i = seg["recording_duration"]
        
        # 可行上限：允許短 range 往整段 recording 拓寬
        # 若 range 本身夠長，就只在 range 內切
        if range_len_i >= L:
            feasible_total_i = min(range_len_i, MAX)
        else:
            # range 太短 → 允許往 recording 擴寬
            feasible_total_i = min(recording_duration_i, MAX)
        
        feasible_total.append(feasible_total_i)
        
        # 每段先取「不超過可行上限」的目標
        base_total_i = min(L, feasible_total_i)
        base_total.append(base_total_i)
    
    S = sum(base_total)
    logger.info(f"[Vlog] Stage 1: 事件數: {N}, baseline 平均長度 L={L:.2f}秒, 基準總長: {S:.2f}秒")
    for idx, (seg, ft, bt) in enumerate(zip(valid_segments, feasible_total, base_total)):
        logger.info(f"[Vlog]   事件 {idx+1} (id={seg['event_id']}): range_len={seg['range_len']:.2f}秒, feasible={ft:.2f}秒 → base_total={bt:.2f}秒")
    
    # ==========================================
    # Stage 2 — 如果 base 總和不等於 T_max，一次線性等比縮放
    # ==========================================
    final_total: List[float] = []  # 最終總長度
    
    if abs(S - max_total) < 0.001:
        # 總和已經等於目標，不用縮放
        final_total = base_total.copy()
        logger.info(f"[Vlog] Stage 2: 基準總長({S:.2f}秒) = 目標時長({max_total:.2f}秒)，無需縮放")
    else:
        # 一次等比縮放到 T_max
        scale = max_total / S
        final_total = [bt * scale for bt in base_total]
        
        logger.info(f"[Vlog] Stage 2: 基準總長({S:.2f}秒) != 目標時長({max_total:.2f}秒)，縮放比例: {scale:.4f}")
        
        # 驗證總長
        actual_total = sum(final_total)
        logger.info(f"[Vlog] Stage 2: 最終總長: {actual_total:.2f}秒 (目標: {max_total:.2f}秒, 誤差: {abs(actual_total - max_total):.2f}秒)")
        for idx, (bt, ft) in enumerate(zip(base_total, final_total)):
            logger.info(f"[Vlog]   事件 {idx+1}: base_total={bt:.2f}秒 → final_total={ft:.2f}秒")
    
    # ==========================================
    # Stage 2.5 — 確保每個片段至少達到平均長度 L（避免一閃而過）
    # 同時確保每個片段至少達到 MIN_SEGMENT_DURATION
    # ==========================================
    
    # 檢查是否有片段小於平均長度 L 或最小長度 MIN
    needs_adjustment = False
    for idx, ft in enumerate(final_total):
        if (ft < L - 0.001 and feasible_total[idx] >= L) or (ft < MIN - 0.001 and feasible_total[idx] >= MIN):
            needs_adjustment = True
            break
    
    if needs_adjustment:
        logger.info(f"[Vlog] Stage 2.5: 檢測到有片段小於平均長度 L={L:.2f}秒，開始重新分配")
        
        # 第一輪：將所有小於 L 或 MIN 且可行上限允許的片段提升到目標長度
        adjusted_total = final_total.copy()
        deficit = 0.0  # 需要補足的總時長
        
        for idx in range(N):
            target_length = max(L, MIN)  # 目標長度取 L 和 MIN 的較大值
            if adjusted_total[idx] < target_length - 0.001 and feasible_total[idx] >= target_length:
                # 需要補足到目標長度
                needed = target_length - adjusted_total[idx]
                adjusted_total[idx] = target_length
                deficit += needed
                logger.info(f"[Vlog]   事件 {idx+1}: 從 {final_total[idx]:.2f}秒 提升到 {target_length:.2f}秒 (需要補 {needed:.2f}秒)")
        
        # 第二輪：從其他片段中扣除多餘的時間來補足 deficit
        if deficit > 0.001:
            # 找出可以縮減的片段（大於 L 且還有縮減空間）
            reducible_segments = []
            for idx in range(N):
                if adjusted_total[idx] > L + 0.001:
                    # 計算可以縮減到的最小值
                    # 如果可行上限 >= L，可以縮減到 L；否則只能縮減到可行上限
                    min_allowed = L if feasible_total[idx] >= L else feasible_total[idx]
                    max_reduction = adjusted_total[idx] - min_allowed
                    if max_reduction > 0.001:
                        reducible_segments.append((idx, max_reduction))
            
            # 按可縮減量排序（從大到小）
            reducible_segments.sort(key=lambda x: x[1], reverse=True)
            
            remaining_deficit = deficit
            for idx, max_reduction in reducible_segments:
                if remaining_deficit <= 0.001:
                    break
                
                # 縮減這個片段
                reduction = min(remaining_deficit, max_reduction)
                adjusted_total[idx] -= reduction
                remaining_deficit -= reduction
                logger.info(f"[Vlog]   事件 {idx+1}: 從 {adjusted_total[idx] + reduction:.2f}秒 縮減到 {adjusted_total[idx]:.2f}秒 (縮減 {reduction:.2f}秒)")
            
            # 如果還有剩餘的 deficit，需要從所有大於 L 的片段中按比例縮減
            if remaining_deficit > 0.001:
                # 找出所有可以縮減的片段（大於 L，且可行上限允許）
                available_segments = []
                for idx in range(N):
                    if adjusted_total[idx] > L + 0.001:
                        # 計算可以縮減的空間
                        min_allowed = L if feasible_total[idx] >= L else feasible_total[idx]
                        available = adjusted_total[idx] - min_allowed
                        if available > 0.001:
                            available_segments.append((idx, available))
                
                if available_segments:
                    total_available = sum(amount for _, amount in available_segments)
                    if total_available > 0.001:
                        # 按比例縮減，但確保不會低於最小值
                        for idx, available in available_segments:
                            reduction = remaining_deficit * (available / total_available)
                            min_allowed = L if feasible_total[idx] >= L else feasible_total[idx]
                            # 確保縮減後不會低於最小值
                            reduction = min(reduction, adjusted_total[idx] - min_allowed)
                            adjusted_total[idx] -= reduction
                            remaining_deficit -= reduction
                            logger.info(f"[Vlog]   事件 {idx+1}: 按比例縮減 {reduction:.2f}秒 → {adjusted_total[idx]:.2f}秒")
            
            # 如果仍然無法補足，記錄警告（理論上不應該發生，因為總時長是固定的）
            if remaining_deficit > 0.001:
                logger.warning(f"[Vlog] Stage 2.5: 無法完全補足 deficit ({remaining_deficit:.2f}秒)，可能因為可行上限限制")
        
        # 驗證調整後的總時長
        adjusted_sum = sum(adjusted_total)
        logger.info(f"[Vlog] Stage 2.5: 調整後總長: {adjusted_sum:.2f}秒 (目標: {max_total:.2f}秒, 誤差: {abs(adjusted_sum - max_total):.2f}秒)")
        
        # 確保每個片段不超過可行上限
        for idx in range(N):
            if adjusted_total[idx] > feasible_total[idx] + 0.001:
                logger.warning(f"[Vlog]   事件 {idx+1}: 調整後長度({adjusted_total[idx]:.2f}秒) 超過可行上限({feasible_total[idx]:.2f}秒)，限制為可行上限")
                adjusted_total[idx] = feasible_total[idx]
        
        final_total = adjusted_total
        
        # 最終驗證：檢查最小值保證
        for idx in range(N):
            if feasible_total[idx] >= L and final_total[idx] < L - 0.001:
                logger.warning(f"[Vlog]   事件 {idx+1}: 最終長度({final_total[idx]:.2f}秒) 仍小於平均長度 L({L:.2f}秒)，但可行上限可能不足")
    else:
        logger.info(f"[Vlog] Stage 2.5: 所有片段都已達到或超過平均長度 L={L:.2f}秒，無需調整")
    
    # ==========================================
    # Stage 3 — 平移置中 window
    # 規則：
    # 1. 計算平均長度 L = max_total / N
    # 2. 如果 range 比平均片段小（range_len < L）：
    #    - 以 range 中點為中心，在 recording_duration 範圍內擴寬至 L
    #    - 如果影片本身比 L 小，則使用整段影片
    # 3. 如果 range 超過平均時間（range_len >= L）：
    #    - 以 range 中點為中心，裁切到 min(L+1, range_len) 的長度
    #    - 必須在 range 內
    # 4. 最終總時長應該等於用戶輸入的時間
    # ==========================================
    prepared: List[Dict[str, Any]] = []
    skipped_segments: List[int] = []  # 記錄被跳過的片段索引（理論上不應該有）
    
    # 計算平均長度
    L = max_total / N if N > 0 else 0.0

    for idx, seg in enumerate(valid_segments):
        range_start_i = seg["range_start"]
        range_end_i = seg["range_end"]
        range_len_i = seg["range_len"]
        recording_duration_i = seg["recording_duration"]
        final_total_i = final_total[idx]
        
        # 使用 Stage1/2/2.5 計算出的 final_total_i 作為目標長度
        target_length = final_total_i
        
        # 一律從事件開始切（左對齊）
        clip_start = range_start_i
        desired_end = clip_start + target_length
        
        if range_len_i >= target_length:
            # range 本身就夠長：在 range 內左對齊裁切
            clip_duration = target_length
            is_expanded = False
            logger.info(
                f"[Vlog] 事件 {idx+1} (id={seg['event_id']}) "
                f"range夠長({range_len_i:.2f} >= target={target_length:.2f})，"
                f"左對齊裁切 {clip_duration:.2f}s"
            )
        else:
            # range 太短：往 recording 後方拓寬
            clip_end = min(desired_end, recording_duration_i)
            clip_duration = clip_end - clip_start
            
            # 如果事件開始點已經太接近影片尾端，導致長度不足
            if clip_duration < MIN_SEGMENT_DURATION and recording_duration_i > MIN_SEGMENT_DURATION:
                # 仍然不往前移（尊重你要從事件開始）
                clip_duration = max(clip_duration, 0.0)
            
            is_expanded = clip_duration > range_len_i + 1e-3
            logger.info(
                f"[Vlog] 事件 {idx+1} (id={seg['event_id']}) "
                f"range較短({range_len_i:.2f} < target={target_length:.2f})，"
                f"從事件開始往後拓寬至 {clip_duration:.2f}s "
                f"(rec_dur={recording_duration_i:.2f})"
            )
        
        # 詳細日誌
        logger.info(
            f"[Vlog]   事件 {idx+1}: "
            f"range_len={range_len_i:.2f}, target={target_length:.2f}, "
            f"rec_dur={recording_duration_i:.2f}, "
            f"clip=[{clip_start:.2f}, {clip_start+clip_duration:.2f}] expanded={is_expanded}"
        )
        
        prepared.append({
            "event_id": seg["event_id"],  # 單個事件 ID（不再 merge）
            "order": idx,
            "bucket": seg["bucket"],
            "object_name": seg["object_name"],
            "clip_start": clip_start,
            "clip_duration": clip_duration,
            "recording_duration": recording_duration_i,
            "is_expanded": is_expanded,  # 標記是否擴寬
            "range_start": range_start_i,  # 保存原始 range 用於驗收
            "range_end": range_end_i,
        })

    # 理論上不應該有片段被跳過（因為現在會嘗試擴寬），但保留檢查
    if skipped_segments:
        logger.warning(f"[Vlog] Stage 3: 跳過了 {len(skipped_segments)} 個片段（理論上不應該發生）")
    
    # 計算總時長（用於日誌記錄）
    total_duration_check = sum(p['clip_duration'] for p in prepared)
    logger.info(f"[Vlog] Stage 3: 總時長: {total_duration_check:.2f}秒 (目標: {max_total:.2f}秒, 誤差: {abs(total_duration_check - max_total):.2f}秒)")

    # ==========================================
    # 驗證與日誌
    # ==========================================
    logger.info(f"[Vlog] Stage 3: 準備了 {len(prepared)} 個片段 (跳過了 {len(skipped_segments)} 個片段)")
    logger.info(f"[Vlog]   預估總時長: {total_duration_check:.2f}秒 (目標: {max_total:.2f}秒, 誤差: {abs(total_duration_check - max_total):.2f}秒)")
    
    # 詳細驗證日誌
    for prep in prepared:
        original_idx = prep["order"]
        seg = valid_segments[original_idx]
        logger.info(f"[Vlog]   事件 {original_idx+1} (id={seg['event_id']}): range_len={seg['range_len']:.2f}秒, clip_duration={prep['clip_duration']:.2f}秒, clip_start={prep['clip_start']:.2f}秒, 擴寬={prep.get('is_expanded', False)}")
    
    # 驗收條件檢查
    total_duration_sum = sum(p['clip_duration'] for p in prepared)
    duration_error = abs(total_duration_sum - max_total)
    if duration_error > 0.1:
        logger.warning(f"[Vlog] 驗收條件: 總時長({total_duration_sum:.2f}秒) 與目標({max_total:.2f}秒) 誤差過大 ({duration_error:.2f}秒)")
    else:
        logger.info(f"[Vlog] 驗收條件: 總時長({total_duration_sum:.2f}秒) 符合目標({max_total:.2f}秒)，誤差: {duration_error:.2f}秒")
    
    for prep in prepared:
        original_idx = prep["order"]
        seg = valid_segments[original_idx]
        clip_start = prep['clip_start']
        clip_duration = prep['clip_duration']
        clip_end = clip_start + clip_duration
        range_start_i = prep.get('range_start', seg['range_start'])
        range_end_i = prep.get('range_end', seg['range_end'])
        recording_duration_i = prep['recording_duration']
        is_expanded = prep.get('is_expanded', False)
        
        # 驗收條件: 
        # - 如果擴寬了，檢查 clip 是否在 recording_duration 內
        # - 如果沒有擴寬，檢查 clip 是否在 range 內
        if is_expanded:
            # 擴寬的情況：檢查是否在 recording_duration 內
            if clip_start < -0.001 or clip_end > recording_duration_i + 0.001:
                logger.error(f"[Vlog] 驗收條件失敗 (事件 {original_idx+1}): 擴寬後的 clip 超出影片範圍 (clip: [{clip_start:.2f}, {clip_end:.2f}], recording_duration: [0.00, {recording_duration_i:.2f}])")
        else:
            # 未擴寬的情況：檢查是否在 range 內
            if clip_start < range_start_i - 0.001 or clip_end > range_end_i + 0.001:
                logger.error(f"[Vlog] 驗收條件失敗 (事件 {original_idx+1}): clip 超出 range (clip: [{clip_start:.2f}, {clip_end:.2f}], range: [{range_start_i:.2f}, {range_end_i:.2f}])")
        
        # 驗收條件: clip_duration 應該 >= MIN_SEGMENT_DURATION（除非影片太短）
        if clip_duration < MIN_SEGMENT_DURATION - 0.001:
            logger.warning(f"[Vlog] 驗收條件警告 (事件 {original_idx+1}): clip_duration({clip_duration:.2f}秒) < MIN({MIN_SEGMENT_DURATION:.2f}秒)")
    
    # ==========================================
    # Stage 4 — Clip 層級的合併（避免同一支影片內的片段重疊）
    # ==========================================
    logger.info(f"[Vlog] Stage 4: 開始 clip 層級合併，合併前有 {len(prepared)} 個片段")
    prepared = _merge_clipped_segments(prepared, merge_gap=0.0)
    logger.info(f"[Vlog] Stage 4: clip 層級合併完成，合併後有 {len(prepared)} 個片段")
    
    # 重新計算總時長
    final_total_duration = sum(p.get('clip_duration', 0) for p in prepared)
    logger.info(f"[Vlog] Stage 4: 最終總時長: {final_total_duration:.2f}秒 (目標: {max_total:.2f}秒, 誤差: {abs(final_total_duration - max_total):.2f}秒)")
    
    return prepared


class VlogGenerationTask(Task):
    """Vlog 生成任務基類"""
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """任務失敗時的回調"""
        logger.error(f"Vlog 生成任務失敗: {exc}")
        
        vlog_id = kwargs.get('vlog_id')
        if vlog_id:
            _update_vlog_status(
                vlog_id,
                status='failed',
                status_message=f"任務失敗: {exc}",
                error_message=str(exc)
            )


@app.task(bind=True, base=VlogGenerationTask, name="tasks.generate_vlog")
def generate_vlog(
    self,
    vlog_id: str = None,
    user_id: int = None,
    event_ids: List[str] = None,
    settings: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    生成 Vlog
    
    Args:
        vlog_id: Vlog ID
        user_id: 用戶 ID
        event_ids: 事件 ID 列表
        settings: 設定 (max_duration, resolution, music_preference)
    """
    logger.info(f"開始生成 Vlog: {vlog_id}")
    logger.info(f"參數檢查: vlog_id={vlog_id}, user_id={user_id}, event_ids_len={len(event_ids) if event_ids else 0}")
    
    if not vlog_id or not user_id or not event_ids:
        logger.error(f"缺少必要參數: vlog_id={vlog_id}, user_id={user_id}, event_ids={event_ids}")
        _update_vlog_status(
            vlog_id,
            status='failed',
            error_message="缺少必要參數",
            status_message="缺少必要參數"
        )
        raise ValueError("缺少必要參數")
    
    progress_state = {"value": 0.0}

    def set_progress(value: float, message: str):
        clamped = max(0.0, min(100.0, float(value)))
        progress_state["value"] = clamped
        _update_vlog_status(
            vlog_id,
            status='processing',
            progress=clamped,
            status_message=message
        )

    try:
        set_progress(2.0, "排程已啟動，準備生成 Vlog")
        logger.info(f"[Vlog] 生成任務參數: vlog_id={vlog_id}, user_id={user_id}, event_ids={event_ids}, settings={settings}")
        
        # 1. 獲取事件對應的錄影片段 (通過 API)
        raw_segments = _get_video_segments(event_ids)
        
        if not raw_segments:
            raise ValueError("沒有找到有效的視頻片段")

        set_progress(5.0, "取得事件與錄影資訊")

        # 2. 按事件順序整理、平均分配時長、中間取片
        # 修復問題 1: 確認 max_duration 是否正確傳入
        raw_max_duration = settings.get('max_duration') if settings else None
        max_duration = float(raw_max_duration if raw_max_duration is not None else 180)
        logger.info(f"[Vlog] max_duration from settings: raw={raw_max_duration}, final={max_duration}, settings keys={list(settings.keys()) if settings else None}")
        video_segments = _prepare_segments(event_ids, raw_segments, max_duration)
        if not video_segments:
            raise ValueError("有效的影片片段不足以生成 Vlog")
        
        # 清理不再需要的大列表
        del raw_segments
        gc.collect()
        
        total_segments = len(video_segments)
        logger.info(f"獲取到 {total_segments} 個有效的視頻片段")
        set_progress(8.0, f"共 {total_segments} 個片段，開始剪輯")
        
        # 3. 下載並剪輯視頻片段
        temp_dir = tempfile.mkdtemp()
        try:
            clip_span = 65.0

            def segment_progress(idx: int, total: int, success: bool):
                total = max(1, total)
                fraction = (idx + 1) / total
                progress_value = 10.0 + clip_span * fraction
                message = f"剪輯影片片段 {idx + 1}/{total}"
                if not success:
                    message += "（跳過）"
                set_progress(progress_value, message)

            clipped_videos = _download_and_clip_segments(
                video_segments,
                temp_dir,
                settings or {},
                progress_callback=segment_progress
            )
            
            # 清理不再需要的片段資訊
            del video_segments
            gc.collect()
            
            if not clipped_videos:
                 raise ValueError("視頻剪輯失敗，沒有生成任何片段")

            # 4. 合併視頻片段
            output_path = os.path.join(temp_dir, f"vlog_{vlog_id}.mp4")
            set_progress(80.0, "剪輯完成，開始合併影片")
            final_duration = _merge_videos(clipped_videos, output_path, settings or {})
            
            # 清理剪輯後的視頻列表（文件仍在，但列表可以釋放）
            del clipped_videos
            gc.collect()
            try:
                output_path = _apply_music_track(output_path, temp_dir, settings or {})
                # 音樂處理完成後清理記憶體
                gc.collect()
            except Exception as exc:
                logger.error(f"[Vlog] 套用背景音樂失敗: {exc}")
            
            # 5. 上傳到 MinIO
            timestamp_slug = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            object_name = f"{user_id}/vlogs/{timestamp_slug}_{vlog_id}.mp4"
            set_progress(92.0, "合併完成，準備上傳")
            set_progress(95.0, "上傳影片中")
            _upload_to_minio(output_path, object_name, 'video/mp4')
            
            # 上傳完成後清理記憶體
            gc.collect()
            
            # 6. 生成並上傳縮圖
            set_progress(97.0, "生成縮圖中")
            thumbnail_s3_key = None
            thumbnail_path = os.path.join(temp_dir, f"vlog_{vlog_id}_thumb.jpg")
            
            if _generate_thumbnail(output_path, thumbnail_path):
                # 檢查縮圖文件是否真的生成成功
                if os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0:
                    try:
                        thumbnail_s3_key = object_name.replace('.mp4', '.jpg').replace('/vlogs/', '/vlog_thumbnails/')
                        _upload_to_minio(thumbnail_path, thumbnail_s3_key, 'image/jpeg')
                        logger.info(f"[Vlog] 縮圖已成功上傳: {thumbnail_s3_key}")
                    except Exception as upload_exc:
                        logger.error(f"[Vlog] 縮圖上傳失敗: {upload_exc}，但繼續執行")
                        thumbnail_s3_key = None  # 上傳失敗時設為 None
                else:
                    logger.warning(f"[Vlog] 縮圖文件生成失敗或文件為空: {thumbnail_path}")
            else:
                logger.warning(f"[Vlog] 縮圖生成失敗，繼續執行")
            
            # 縮圖處理完成後清理記憶體
            gc.collect()
            
            # 7. 更新狀態為完成 (通過 API，包含縮圖路徑)
            progress_state["value"] = 100.0
            _update_vlog_status(
                vlog_id,
                status='completed',
                s3_key=object_name,
                duration=final_duration,
                progress=100.0,
                status_message="Vlog 生成完成",
                thumbnail_s3_key=thumbnail_s3_key
            )
            
            logger.info(f"Vlog 生成成功: {vlog_id}")
            
            return {
                "vlog_id": vlog_id,
                "s3_key": object_name,
                "duration": final_duration,
                "status": "completed"
            }
            
        finally:
            # 清理臨時文件
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"[Vlog] 臨時目錄已清理: {temp_dir}")
            except Exception as e:
                logger.warning(f"清理臨時文件失敗: {e}")
            
            # 強制垃圾回收，釋放所有記憶體
            gc.collect()
    
    except Exception as e:
        logger.error(f"生成 Vlog 時發生錯誤: {e}", exc_info=True)
        _update_vlog_status(
            vlog_id,
            status='failed',
            error_message=str(e),
            progress=progress_state["value"],
            status_message=f"生成失敗: {e}"
        )
        raise


def _download_and_clip_segments(
    segments: List[Dict[str, Any]], 
    temp_dir: str, 
    settings: Dict[str, Any],
    progress_callback: Callable[[int, int, bool], None] | None = None,
) -> List[str]:
    """
    下載並剪輯視頻片段
    
    progress_callback: 在每個片段完成（或失敗）時回報進度 (idx, total, success)
    
    Returns:
        剪輯後的視頻文件路徑列表
    """
    from minio import Minio
    
    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE
    )
    
    clipped_videos = []
    resolution = settings.get('resolution', '1080p')
    
    # 解析解析度
    resolution_map = {
        '480p': '854:480',
        '720p': '1280:720',
        '1080p': '1920:1080'
    }
    scale = resolution_map.get(resolution, '1280:720')
    
    for idx, segment in enumerate(segments):
        try:
            # 下載原始視頻
            bucket_name = segment["bucket"]
            object_name = segment["object_name"]
            event_id = segment.get("event_id")
            
            # 先檢查物件是否存在
            try:
                client.stat_object(bucket_name, object_name)
            except Exception as stat_err:
                error_msg = f"S3 物件不存在: bucket={bucket_name}, object={object_name}, event_id={event_id}"
                logger.error(f"[Vlog] {error_msg}, 錯誤: {stat_err}")
                if progress_callback:
                    try:
                        progress_callback(idx, len(segments), False)
                    except Exception as cb_err:
                        logger.debug(f"進度回調錯誤: {cb_err}")
                continue
            
            input_path = os.path.join(temp_dir, f"input_{idx}.mp4")
            client.fget_object(bucket_name, object_name, input_path)
            
            # 使用 FFmpeg 剪輯視頻
            output_path = os.path.join(temp_dir, f"clip_{idx}.mp4")
            start_time = segment['clip_start']
            duration = segment['clip_duration']
            
            # FFmpeg 命令：移除原始音軌（-an），只保留影像
            cmd = [
                'ffmpeg', '-y',
                '-ss', str(start_time),
                '-i', input_path,
                '-t', str(duration),
                '-vf', f'scale={scale}',
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-an',  # 刪除原始音軌
                output_path
            ]
            
            subprocess.run(cmd, check=True, capture_output=True)
            clipped_videos.append(output_path)
            
            # 刪除輸入文件以節省空間
            try:
                os.remove(input_path)
            except Exception as e:
                logger.warning(f"刪除臨時輸入文件失敗: {e}")
            
            # 每處理 5 個片段後進行一次垃圾回收
            if (idx + 1) % 5 == 0:
                gc.collect()
            
            if progress_callback:
                try:
                    progress_callback(idx, len(segments), True)
                except Exception as cb_err:
                    logger.debug(f"進度回調錯誤: {cb_err}")
            
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error(f"[Vlog] 處理片段 {idx} (event {event_id}) 時出錯: {error_type}: {error_msg}")
            logger.error(f"[Vlog] 片段詳情: bucket={segment.get('bucket')}, object={segment.get('object_name')}, clip_start={segment.get('clip_start')}, clip_duration={segment.get('clip_duration')}")
            
            # 如果是 S3 錯誤，提供更詳細的信息
            if "NoSuchKey" in error_msg or "Object does not exist" in error_msg:
                logger.error(f"[Vlog] S3 物件不存在，可能原因：")
                logger.error(f"[Vlog]   1. 影片檔案已被刪除")
                logger.error(f"[Vlog]   2. 資料庫中的 s3_key 與實際 S3 檔案不一致")
                logger.error(f"[Vlog]   3. 檔案上傳失敗但事件記錄已建立")
            
            if progress_callback:
                try:
                    progress_callback(idx, len(segments), False)
                except Exception as cb_err:
                    logger.debug(f"進度回調錯誤: {cb_err}")
            continue
    
    # 所有片段處理完成後，進行最終垃圾回收
    gc.collect()
    return clipped_videos


def _merge_videos(
    video_files: List[str], 
    output_path: str, 
    settings: Dict[str, Any]
) -> float:
    """
    合併多個視頻文件
    
    Returns:
        最終視頻的時長 (秒)
    """
    if not video_files:
        raise ValueError("沒有視頻文件可以合併")
    
    # 創建 concat 文件
    concat_file = output_path + '.txt'
    with open(concat_file, 'w') as f:
        for video_file in video_files:
            f.write(f"file '{video_file}'\n")
    
    try:
        # 使用 FFmpeg concat
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', concat_file,
            '-c', 'copy',
            output_path
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        
        # 獲取視頻時長
        duration_cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            output_path
        ]
        
        result = subprocess.run(duration_cmd, capture_output=True, text=True, check=True)
        duration = float(result.stdout.strip())
        
        # 不再做超過 max_duration 的 trim，因為總長已在剪片前控制好
        # 只保留異常情況的 safeguard（如果超過太多，記錄警告但不裁剪）
        max_duration = settings.get('max_duration', 180) if settings else 180
        if duration > max_duration * 1.1:  # 允許 10% 的誤差
            logger.warning(f"[Vlog] 合併後的影片時長 ({duration:.2f}秒) 超過預期 ({max_duration}秒)，但已在剪片階段控制，不進行裁剪")
        
        return duration
        
    finally:
        # 清理 concat 文件
        if os.path.exists(concat_file):
            try:
                os.remove(concat_file)
            except Exception as e:
                logger.warning(f"刪除 concat 文件失敗: {e}")
        
        # 合併完成後清理記憶體
        del video_files
        gc.collect()


def _generate_thumbnail(video_path: str, thumbnail_path: str) -> bool:
    """
    從視頻第一幀生成縮圖
    
    Args:
        video_path: 視頻文件路徑
        thumbnail_path: 縮圖輸出路徑
    
    Returns:
        True 如果生成成功，False 如果失敗
    """
    try:
        # 檢查視頻文件是否存在
        if not os.path.exists(video_path):
            logger.error(f"[Vlog] 視頻文件不存在: {video_path}")
            return False
        
        # 使用 FFmpeg 提取第一幀
        cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-ss', '00:00:00',
            '-vframes', '1',
            '-vf', 'scale=320:-1',  # 縮放寬度為 320，高度自動
            '-q:v', '2',  # 高質量
            thumbnail_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
        
        # 驗證縮圖文件是否生成成功
        if os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0:
            logger.info(f"[Vlog] 縮圖生成成功: {thumbnail_path} (大小: {os.path.getsize(thumbnail_path)} bytes)")
            return True
        else:
            logger.error(f"[Vlog] 縮圖文件生成失敗或為空: {thumbnail_path}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"[Vlog] 生成縮圖超時: {video_path}")
        return False
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        logger.error(f"[Vlog] 生成縮圖失敗 (FFmpeg 錯誤): {error_msg}")
        return False
    except Exception as e:
        logger.error(f"[Vlog] 生成縮圖時發生錯誤: {e}", exc_info=True)
        return False


def _apply_music_track(
    video_path: str,
    temp_dir: str,
    settings: Dict[str, Any],
) -> str:
    """將背景音樂與影片合成"""
    logger.info(f"[Vlog] 開始套用背景音樂，settings: {settings}")
    music_cfg = (settings or {}).get("music") or {}
    logger.info(f"[Vlog] 音樂設定: {music_cfg}")
    s3_key = music_cfg.get("s3_key")
    if not s3_key:
        logger.warning(f"[Vlog] 沒有音樂 s3_key，跳過音樂處理")
        return video_path

    from minio import Minio

    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE
    )

    # s3_key 格式通常是 {user_id}/music/{filename}，bucket 固定為 MINIO_BUCKET
    # 如果 s3_key 包含 s3:// 前綴，則解析它；否則直接使用 MINIO_BUCKET
    if s3_key.startswith("s3://"):
        try:
            bucket, object_name = _parse_s3_path(s3_key)
        except ValueError as exc:
            logger.error(f"[Vlog] 音樂 s3_key 解析失敗: {exc}")
            return video_path
    else:
        # 直接使用 MINIO_BUCKET，整個 s3_key 作為 object_name
        bucket = MINIO_BUCKET
        object_name = s3_key

    logger.info(f"[Vlog] 音樂下載資訊: bucket={bucket}, object_name={object_name}")
    
    audio_ext = os.path.splitext(object_name)[1] or ".mp3"
    music_source_path = os.path.join(temp_dir, f"music_source{audio_ext}")
    try:
        client.fget_object(bucket, object_name, music_source_path)
        logger.info(f"[Vlog] 音樂下載成功: {music_source_path}")
    except Exception as exc:
        logger.error(f"[Vlog] 下載背景音樂失敗: {exc}")
        return video_path

    start_time = float(music_cfg.get("start") or 0.0)
    end_time = float(music_cfg.get("end") or 0.0)
    if end_time <= start_time:
        logger.warning("[Vlog] 音樂選取範圍無效，忽略背景音樂")
        return video_path

    clip_duration = max(end_time - start_time, 1.0)
    music_clip_path = os.path.join(temp_dir, "music_clip.m4a")
    trim_cmd = [
        'ffmpeg', '-y',
        '-ss', f"{max(start_time, 0.0):.3f}",
        '-i', music_source_path,
        '-t', f"{clip_duration:.3f}",
        '-acodec', 'aac',
        '-b:a', '192k',
        music_clip_path
    ]

    try:
        subprocess.run(trim_cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        logger.error(f"[Vlog] 音樂裁剪失敗: {exc.stderr.decode(errors='ignore')}")
        return video_path

    volume = float(music_cfg.get("volume")) if music_cfg.get("volume") is not None else 0.6
    volume = max(0.0, min(1.0, volume))

    # 先獲取影片的實際長度，確保音樂長度匹配影片
    video_duration_cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        video_path
    ]
    
    video_duration = None
    try:
        result = subprocess.run(video_duration_cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            video_duration = float(result.stdout.strip())
            logger.info(f"[Vlog] 影片實際長度: {video_duration:.2f}秒")
    except Exception as exc:
        logger.warning(f"[Vlog] 無法獲取影片長度: {exc}，將使用音樂長度")
    
    # 如果影片長度已知，調整音樂長度以匹配影片（循環或裁切）
    processed_music_path = os.path.join(temp_dir, "music_processed.m4a")
    audio_input_path = music_clip_path
    
    if video_duration and video_duration > 0:
        if clip_duration < video_duration:
            # 音樂比影片短，需要循環播放
            logger.info(f"[Vlog] 音樂長度({clip_duration:.2f}秒) < 影片長度({video_duration:.2f}秒)，將循環播放音樂")
            # 重新生成音樂，循環到影片長度
            looped_music_path = os.path.join(temp_dir, "music_looped.m4a")
            loop_count = int(video_duration / clip_duration) + 1
            loop_filter = f"aloop=loop={loop_count}:size=2e+09"
            loop_cmd = [
                'ffmpeg', '-y',
                '-i', music_clip_path,
                '-af', loop_filter,
                '-t', f"{video_duration:.3f}",
                '-acodec', 'aac',
                '-b:a', '192k',
                looped_music_path
            ]
            try:
                subprocess.run(loop_cmd, check=True, capture_output=True, timeout=30)
                audio_input_path = looped_music_path
                logger.info(f"[Vlog] 音樂已循環到 {video_duration:.2f}秒")
            except Exception as exc:
                logger.warning(f"[Vlog] 音樂循環失敗: {exc}，使用原始音樂")
                audio_input_path = music_clip_path
        elif clip_duration > video_duration:
            # 音樂比影片長，裁切音樂到影片長度
            logger.info(f"[Vlog] 音樂長度({clip_duration:.2f}秒) > 影片長度({video_duration:.2f}秒)，將裁切音樂")
            trimmed_music_path = os.path.join(temp_dir, "music_trimmed.m4a")
            trim_cmd = [
                'ffmpeg', '-y',
                '-i', music_clip_path,
                '-t', f"{video_duration:.3f}",
                '-acodec', 'copy',
                trimmed_music_path
            ]
            try:
                subprocess.run(trim_cmd, check=True, capture_output=True, timeout=30)
                audio_input_path = trimmed_music_path
                logger.info(f"[Vlog] 音樂已裁切到 {video_duration:.2f}秒")
            except Exception as exc:
                logger.warning(f"[Vlog] 音樂裁切失敗: {exc}，使用原始音樂")
                audio_input_path = music_clip_path
        else:
            # 音樂長度剛好等於影片長度
            audio_input_path = music_clip_path
    else:
        # 無法獲取影片長度，使用原始音樂
        audio_input_path = music_clip_path
        video_duration = clip_duration  # 使用音樂長度作為預設值
    
    # 根據最終影片實際時長進行淡入淡出（在音樂長度已匹配影片後）
    fade_enabled = bool(music_cfg.get("fade", True))
    final_duration = video_duration if video_duration else clip_duration
    fade_duration = min(2.0, final_duration / 2.0)
    
    if fade_enabled and fade_duration > 0 and final_duration > 0:
        # 淡入：從第 0 秒開始，持續 fade_duration 秒
        # 淡出：從 (final_duration - fade_duration) 秒開始，持續 fade_duration 秒
        fade_filters = [
            f"afade=t=in:st=0:d={fade_duration:.3f}",
            f"afade=t=out:st={max(final_duration - fade_duration, 0):.3f}:d={fade_duration:.3f}",
        ]
        filter_expr = ",".join(fade_filters)
        fade_cmd = [
            'ffmpeg', '-y',
            '-i', audio_input_path,
            '-af', filter_expr,
            '-acodec', 'aac',
            '-b:a', '192k',
            processed_music_path
        ]
        try:
            subprocess.run(fade_cmd, check=True, capture_output=True, timeout=30)
            audio_input_path = processed_music_path
            logger.info(f"[Vlog] 音樂淡入淡出已應用：淡入 0-{fade_duration:.2f}秒，淡出 {final_duration - fade_duration:.2f}-{final_duration:.2f}秒")
        except subprocess.CalledProcessError as exc:
            logger.warning(f"[Vlog] 音樂淡入淡出處理失敗: {exc.stderr.decode(errors='ignore')}")
            # 繼續使用未處理淡入淡出的音樂

    mixed_output_path = os.path.join(temp_dir, "vlog_with_music.mp4")
    
    # 檢查影片是否有音軌
    check_audio_cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'a:0',
        '-show_entries', 'stream=codec_type',
        '-of', 'csv=p=0',
        video_path
    ]
    
    has_audio = False
    try:
        result = subprocess.run(check_audio_cmd, capture_output=True, text=True, timeout=5)
        has_audio = result.returncode == 0 and result.stdout.strip() == 'audio'
    except Exception:
        has_audio = False
    
    if has_audio:
        # 影片有音軌，進行混音
        # 使用 duration=first 確保以影片長度為準（而不是 shortest）
        mix_filter = (
            f"[0:a]volume=1.0[a0];"
            f"[1:a]volume={volume:.2f}[a1];"
            f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        mix_cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-i', audio_input_path,
            '-filter_complex', mix_filter,
            '-map', '0:v',
            '-map', 'aout',
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-b:a', '192k',
            mixed_output_path
        ]
    else:
        # 影片沒有音軌，直接添加音樂
        # 不使用 -shortest，而是以影片長度為準
        mix_cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-i', audio_input_path,
            '-filter_complex', f"[1:a]volume={volume:.2f}[a1]",
            '-map', '0:v',
            '-map', '[a1]',
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-b:a', '192k',
            mixed_output_path
        ]

    try:
        subprocess.run(mix_cmd, check=True, capture_output=True, timeout=300)
        logger.info(f"[Vlog] 音樂已成功加入影片")
    except subprocess.CalledProcessError as exc:
        error_msg = exc.stderr.decode(errors='ignore') if exc.stderr else '未知錯誤'
        logger.error(f"[Vlog] 混音失敗: {error_msg}")
        # 如果混音失敗，嘗試使用後備方案（直接替換音軌）
        fallback_cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-i', audio_input_path,
            '-map', '0:v',
            '-map', '1:a',
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-b:a', '192k',
            mixed_output_path
        ]
        try:
            subprocess.run(fallback_cmd, check=True, capture_output=True, timeout=300)
            logger.info(f"[Vlog] 使用後備方案成功加入音樂")
        except Exception as fallback_exc:
            logger.error(f"[Vlog] 後備方案也失敗: {fallback_exc}")
            return video_path
    except subprocess.TimeoutExpired:
        logger.error(f"[Vlog] 混音超時")
        return video_path

    try:
        os.replace(mixed_output_path, video_path)
    except Exception as exc:
        logger.error(f"[Vlog] 更新影片檔案失敗: {exc}")
    finally:
        # 清理臨時音樂文件（混音完成後，所有臨時文件都可以清理）
        cleanup_paths = [
            music_source_path,
            music_clip_path,
        ]
        # 檢查並清理處理後的音樂文件
        if os.path.exists(processed_music_path) and processed_music_path != audio_input_path:
            # 如果 processed_music_path 不是最終使用的文件，可以清理
            # 但實際上，如果淡入淡出成功，processed_music_path 就是最終使用的文件
            # 所以這裡只清理明顯不需要的文件
            pass  # processed_music_path 可能還在混音中使用，不清理
        
        # 檢查並清理循環或裁切後的音樂文件
        looped_path = os.path.join(temp_dir, "music_looped.m4a")
        trimmed_path = os.path.join(temp_dir, "music_trimmed.m4a")
        # 如果這些文件不是最終使用的文件，可以清理
        # 但由於混音已經完成，這些文件都可以清理
        if os.path.exists(looped_path) and looped_path != audio_input_path:
            cleanup_paths.append(looped_path)
        if os.path.exists(trimmed_path) and trimmed_path != audio_input_path:
            cleanup_paths.append(trimmed_path)
        
        for cleanup_path in cleanup_paths:
            if cleanup_path and os.path.exists(cleanup_path):
                try:
                    # 確保不是最終使用的文件
                    if cleanup_path != audio_input_path and cleanup_path != mixed_output_path:
                        os.remove(cleanup_path)
                except Exception:
                    pass
        
        # 清理臨時變數
        del cleanup_paths
        del music_source_path
        del music_clip_path
        del audio_input_path
        if 'looped_path' in locals():
            del looped_path
        if 'trimmed_path' in locals():
            del trimmed_path
        if 'processed_music_path' in locals():
            del processed_music_path
        
        # 音樂處理完成後進行垃圾回收
        gc.collect()

    return video_path


def _upload_to_minio(file_path: str, s3_key: str, content_type: str = 'video/mp4'):
    """
    上傳文件到 MinIO
    
    Args:
        file_path: 本地文件路徑
        s3_key: S3 對象鍵
        content_type: 文件 MIME 類型
    
    Raises:
        FileNotFoundError: 如果文件不存在
        Exception: 如果上傳失敗
    """
    from minio import Minio
    from minio.error import S3Error
    
    # 檢查文件是否存在
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"要上傳的文件不存在: {file_path}")
    
    file_size = os.path.getsize(file_path)
    if file_size == 0:
        raise ValueError(f"要上傳的文件為空: {file_path}")
    
    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE
    )
    
    bucket_name = MINIO_BUCKET
    
    try:
        # 確保 bucket 存在
        if not client.bucket_exists(bucket_name):
            client.make_bucket(bucket_name)
            logger.info(f"[MinIO] 創建 bucket: {bucket_name}")
        
        # 上傳文件
        client.fput_object(
            bucket_name,
            s3_key,
            file_path,
            content_type=content_type
        )
        
        logger.info(f"[MinIO] 已上傳到 MinIO: {bucket_name}/{s3_key} (大小: {file_size} bytes)")
        
    except S3Error as e:
        logger.error(f"[MinIO] S3 錯誤: {e}")
        raise
    except Exception as e:
        logger.error(f"[MinIO] 上傳失敗: {e}")
        raise

