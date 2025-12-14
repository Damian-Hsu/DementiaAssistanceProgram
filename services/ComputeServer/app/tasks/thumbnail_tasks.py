"""
縮圖生成任務
為錄影和 Vlog 生成縮圖
"""
import os
import logging
import tempfile
import subprocess
from typing import Optional
from celery import Task
from ..main import app
import cv2
import requests

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


def _get_video_url_from_api(recording_id: str) -> Optional[str]:
    """通過 API 獲取錄影的 S3 URL"""
    try:
        response = requests.get(
            f"{API_BASE_URL}/recordings/{recording_id}",
            headers=API_HEADERS,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        return data.get("s3_key") or data.get("video_url")
    except Exception as e:
        logger.error(f"獲取錄影 URL 失敗: {e}")
        return None


def _generate_thumbnail_from_url(video_url: str, thumbnail_path: str) -> bool:
    """
    從視頻 URL 生成縮圖
    
    Args:
        video_url: 視頻 URL (可以是 s3:// 或 http://)
        thumbnail_path: 縮圖輸出路徑
    
    Returns:
        是否成功生成
    """
    try:
        # 若是 s3://，優先用 MinIO 內網直接下載到本地再取幀（避免 presigned API/權限問題）
        local_video_path = None
        if video_url.startswith("s3://"):
            try:
                from minio import Minio
                from urllib.parse import urlparse
                # s3://bucket/key
                parsed = urlparse(video_url)
                bucket = (parsed.netloc or "").strip()
                key = (parsed.path or "").lstrip("/")
                if not bucket or not key:
                    raise ValueError(f"invalid s3 url: {video_url}")

                client = Minio(
                    MINIO_ENDPOINT,
                    access_key=MINIO_ACCESS_KEY,
                    secret_key=MINIO_SECRET_KEY,
                    secure=MINIO_SECURE,
                )

                local_video_path = os.path.join(os.path.dirname(thumbnail_path), "source.mp4")
                resp = client.get_object(bucket, key)
                try:
                    with open(local_video_path, "wb") as f:
                        for d in resp.stream(1024 * 1024):
                            f.write(d)
                finally:
                    resp.close()
                    resp.release_conn()

                video_url = local_video_path
            except Exception as e:
                logger.error(f"從 MinIO 下載影片失敗: {e}", exc_info=True)
                return False
        
        # 使用 OpenCV 讀取視頻第一幀
        cap = cv2.VideoCapture(video_url)
        if not cap.isOpened():
            logger.error(f"無法打開視頻: {video_url}")
            return False
        
        ret, frame = cap.read()
        cap.release()
        
        if not ret or frame is None:
            logger.error(f"無法讀取視頻第一幀: {video_url}")
            return False
        
        # 縮放圖片（寬度 320，高度按比例）
        height, width = frame.shape[:2]
        new_width = 320
        new_height = int(height * (new_width / width))
        frame_resized = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
        
        # 保存為 JPEG
        cv2.imwrite(thumbnail_path, frame_resized, [cv2.IMWRITE_JPEG_QUALITY, 85])
        logger.info(f"縮圖生成成功: {thumbnail_path}")
        return True
        
    except Exception as e:
        logger.error(f"生成縮圖失敗: {e}", exc_info=True)
        return False


def _upload_thumbnail_to_minio(thumbnail_path: str, s3_key: str):
    """上傳縮圖到 MinIO"""
    from minio import Minio
    
    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE
    )
    
    bucket_name = MINIO_BUCKET
    
    # 確保 bucket 存在
    if not client.bucket_exists(bucket_name):
        client.make_bucket(bucket_name)
    
    # 上傳文件
    client.fput_object(
        bucket_name,
        s3_key,
        thumbnail_path,
        content_type='image/jpeg'
    )
    
    logger.info(f"縮圖已上傳到 MinIO: {bucket_name}/{s3_key}")


def _update_recording_thumbnail(recording_id: str, thumbnail_s3_key: str):
    """通過 API 更新錄影的縮圖路徑"""
    try:
        response = requests.patch(
            f"{API_BASE_URL}/m2m/recordings/{recording_id}/thumbnail",
            params={"thumbnail_s3_key": thumbnail_s3_key},
            headers=API_HEADERS,
            timeout=10
        )
        response.raise_for_status()
        logger.info(f"錄影縮圖路徑已更新: {recording_id} -> {thumbnail_s3_key}")
    except Exception as e:
        logger.error(f"更新錄影縮圖路徑失敗: {e}")


class ThumbnailTask(Task):
    """縮圖生成任務基類"""
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """任務失敗時的回調"""
        logger.error(f"縮圖生成任務失敗: {exc}")


@app.task(bind=True, base=ThumbnailTask, name="tasks.generate_video_thumbnail")
def generate_video_thumbnail(
    self,
    recording_id: str = None,
    video_url: str = None,
    user_id: int = None
) -> dict:
    """
    為錄影生成縮圖
    
    Args:
        recording_id: 錄影 ID
        video_url: 視頻 URL (可選，如果不提供則從 API 獲取)
        user_id: 用戶 ID (可選，如果不提供則從 API 獲取)
    
    Returns:
        任務結果
    """
    logger.info(f"開始生成錄影縮圖: recording_id={recording_id}")
    
    if not recording_id:
        logger.error("缺少 recording_id")
        return {"success": False, "error": "缺少 recording_id"}
    
    # 獲取視頻 URL
    if not video_url:
        video_url = _get_video_url_from_api(recording_id)
        if not video_url:
            logger.error(f"無法獲取錄影 URL: {recording_id}")
            return {"success": False, "error": "無法獲取錄影 URL"}
    
    # 生成縮圖
    temp_dir = tempfile.mkdtemp()
    try:
        thumbnail_path = os.path.join(temp_dir, f"thumb_{recording_id}.jpg")
        
        if not _generate_thumbnail_from_url(video_url, thumbnail_path):
            return {"success": False, "error": "縮圖生成失敗"}
        
        # 計算縮圖 S3 路徑
        # 從 video_url 提取原始路徑
        if video_url.startswith("s3://"):
            # s3://bucket/user_id/videos/...
            parts = video_url.split("/")
            if len(parts) >= 4:
                user_id_from_url = parts[3]  # user_id
                video_filename = parts[-1]  # 文件名
                thumbnail_filename = video_filename.replace('.mp4', '.jpg').replace('.MP4', '.jpg')
                thumbnail_s3_key = f"{user_id_from_url}/video_thumbnails/{thumbnail_filename}"
            else:
                logger.error(f"無法從 URL 解析路徑: {video_url}")
                return {"success": False, "error": "無法解析視頻路徑"}
        else:
            # 如果沒有 user_id，嘗試從 API 獲取
            if not user_id:
                try:
                    response = requests.get(
                        f"{API_BASE_URL}/recordings/{recording_id}",
                        headers=API_HEADERS,
                        timeout=10
                    )
                    if response.status_code == 200:
                        data = response.json()
                        user_id = data.get("user_id")
                except Exception as e:
                    logger.warning(f"獲取 user_id 失敗: {e}")
            
            if not user_id:
                logger.error("無法獲取 user_id")
                return {"success": False, "error": "無法獲取 user_id"}
            
            # 從 video_url 提取文件名
            video_filename = os.path.basename(video_url.split("?")[0])  # 去掉查詢參數
            thumbnail_filename = video_filename.replace('.mp4', '.jpg').replace('.MP4', '.jpg')
            thumbnail_s3_key = f"{user_id}/video_thumbnails/{thumbnail_filename}"
        
        # 上傳縮圖
        _upload_thumbnail_to_minio(thumbnail_path, thumbnail_s3_key)
        
        # 更新資料庫
        _update_recording_thumbnail(recording_id, thumbnail_s3_key)
        
        logger.info(f"錄影縮圖生成成功: {recording_id} -> {thumbnail_s3_key}")
        return {
            "success": True,
            "recording_id": recording_id,
            "thumbnail_s3_key": thumbnail_s3_key
        }
        
    except Exception as e:
        logger.error(f"生成錄影縮圖時發生錯誤: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
    finally:
        # 清理臨時文件
        try:
            import shutil
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.warning(f"清理臨時文件失敗: {e}")

