"""MinIO 客戶端配置"""
import os
from minio import Minio
from dotenv import load_dotenv

load_dotenv()

# MinIO 配置
_raw_minio_endpoint = os.getenv("MINIO_ENDPOINT", "localhost:30300")
if "://" in _raw_minio_endpoint:
    _scheme, _endpoint = _raw_minio_endpoint.split("://", 1)
    MINIO_ENDPOINT = _endpoint
    MINIO_SECURE = _scheme.lower() == "https"
else:
    MINIO_ENDPOINT = _raw_minio_endpoint
    MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin")

_minio_client = None

def get_minio_client() -> Minio:
    """獲取 MinIO 客戶端單例"""
    global _minio_client
    if _minio_client is None:
        _minio_client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE
        )
    return _minio_client

def ensure_bucket_exists(bucket_name: str):
    """確保 bucket 存在"""
    client = get_minio_client()
    if not client.bucket_exists(bucket_name):
        client.make_bucket(bucket_name)
        print(f"[MinIO] 已創建 bucket: {bucket_name}")

