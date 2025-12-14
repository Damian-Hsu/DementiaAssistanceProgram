from __future__ import annotations

import os
from io import BytesIO
from typing import Optional, BinaryIO

import boto3
from botocore.config import Config


MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "media-bucket")
S3_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", os.getenv("S3_ACCESS_KEY", "minioadmin"))
S3_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", os.getenv("S3_SECRET_KEY", "minioadmin"))
S3_REGION = os.getenv("AWS_REGION", "us-east-1")

# 獲取 MinIO 公開端點（用於生成 presigned URL）
# 優先使用新的環境變數配置，否則使用舊的 MINIO_PUBLIC_ENDPOINT
def _get_minio_public_endpoint() -> str:
    """獲取 MinIO 公開端點，用於生成 presigned URL"""
    # 嘗試使用新的配置方式
    minio_domain = os.getenv("MINIO_PUBLIC_DOMAIN", "").strip()
    if minio_domain:
        scheme = os.getenv("MINIO_PUBLIC_SCHEME", "http").strip()
        port_str = os.getenv("MINIO_PUBLIC_PORT", "").strip()
        
        if port_str:
            try:
                port = int(port_str)
                if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
                    return f"{scheme}://{minio_domain}"
                return f"{scheme}://{minio_domain}:{port}"
            except ValueError:
                pass
        
        return f"{scheme}://{minio_domain}"
    
    # 向後兼容：使用舊的環境變數
    old_endpoint = os.getenv("MINIO_PUBLIC_ENDPOINT", "")
    if old_endpoint:
        return old_endpoint
    
    # 如果完全沒有設定，嘗試從 MINIO_PUBLIC_DOMAIN 構建（即使為空也嘗試）
    # 這確保至少有一個值，避免空字串導致錯誤
    # 注意：生產環境應該在 .env 中明確設定
    return ""  # 返回空字串會在使用時觸發錯誤，提醒設定環境變數

MINIO_PUBLIC_ENDPOINT = _get_minio_public_endpoint()

_s3_internal = boto3.client(
    "s3",
    endpoint_url=MINIO_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    region_name=S3_REGION,
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)

_s3_public = None


def _get_public_client(request: Optional[Request] = None):
    global _s3_public
    if _s3_public is None:
        # 如果公開端點未設定，使用內部端點（但會記錄警告）
        endpoint_url = MINIO_PUBLIC_ENDPOINT if MINIO_PUBLIC_ENDPOINT else MINIO_ENDPOINT
        if not MINIO_PUBLIC_ENDPOINT:
            print("[WARNING] MINIO_PUBLIC_ENDPOINT not set, using internal endpoint. External access may fail.")
        
        # 注意：MinIO 的 presigned URLs 簽名是基於完整路徑的
        # 如果通過 Nginx 代理，路徑會被重寫，導致簽名驗證失敗
        # 解決方案：不使用 Nginx 代理路徑，直接使用 MinIO 的公開端口
        # 或者：配置 MinIO 使用路徑前綴（但 MinIO 不支持）
        # 因此，我們需要直接暴露 MinIO 端口，或者使用不同的方法
        
        # 檢查是否通過 Nginx 代理（端口 80/443）
        from urllib.parse import urlparse
        parsed = urlparse(endpoint_url)
        if parsed.port is None or parsed.port in (80, 443):
            # 通過 Nginx 代理時，presigned URLs 無法正常工作
            # 因為簽名是基於路徑的，而 Nginx 會重寫路徑
            # 解決方案：使用 MinIO 的直接端口（30300）作為公開端點
            # 或者：通過 API 端點代理文件請求，而不是使用 presigned URLs
            print("[WARNING] MinIO presigned URLs cannot work through Nginx proxy due to path rewriting.")
            print("[WARNING] Consider using direct MinIO port (30300) or API proxy for file access.")
            # 暫時使用直接端口作為 fallback
            # 如果環境變數中設定了 MINIO_DIRECT_PORT，使用它
            direct_port = os.getenv("MINIO_DIRECT_PORT", "30300")
            endpoint_url = f"{parsed.scheme}://{parsed.hostname}:{direct_port}"
            print(f"[INFO] Using direct MinIO endpoint: {endpoint_url}")
        
        _s3_public = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            region_name=S3_REGION,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
    return _s3_public


def normalize_s3_key(key: str) -> str:
    if not key:
        raise ValueError("S3 key cannot be empty")

    if key.startswith("s3://"):
        without_scheme = key.split("://", 1)[1]
        if "/" in without_scheme:
            without_scheme = without_scheme.split("/", 1)[1]
        key = without_scheme

    bucket_prefixes = {MINIO_BUCKET, "media-bucket"}
    env_bucket = os.getenv("S3_BUCKET")
    if env_bucket:
        bucket_prefixes.add(env_bucket)

    for prefix in bucket_prefixes:
        if prefix and key.startswith(f"{prefix}/"):
            key = key[len(prefix) + 1 :]
            break

    key = key.strip("/")
    while "//" in key:
        key = key.replace("//", "/")
    key = key.strip()

    if not key:
        raise ValueError("Normalized S3 key is empty after processing")
    return key


def generate_presigned_url(
    object_key: str,
    ttl: int,
    *,
    bucket: Optional[str] = None,
    content_type: Optional[str] = None,
    content_disposition: Optional[str] = None,
    request: Optional[Request] = None,
) -> str:
    normalized_key = normalize_s3_key(object_key)
    params = {
        "Bucket": bucket or MINIO_BUCKET,
        "Key": normalized_key,
    }
    if content_type:
        params["ResponseContentType"] = content_type
    if content_disposition:
        params["ResponseContentDisposition"] = content_disposition

    # 如果公開端點未設定，使用內部端點（但這會導致外部無法訪問）
    # 建議在 .env 中設定 MINIO_PUBLIC_DOMAIN
    if MINIO_PUBLIC_ENDPOINT and MINIO_PUBLIC_ENDPOINT != MINIO_ENDPOINT:
        client = _get_public_client(request)
    else:
        # 如果公開端點未設定，記錄警告但繼續使用內部端點
        if not MINIO_PUBLIC_ENDPOINT:
            print("[WARNING] MINIO_PUBLIC_ENDPOINT not set, using internal endpoint. External access may fail.")
        client = _s3_internal

    presigned_url = client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=int(ttl),
    )
    
    # 如果使用 Nginx 代理，presigned URL 應該已經包含 /minio/ 前綴
    # 因為我們在 _get_public_client 中已經將 endpoint_url 設置為包含 /minio 路徑
    # 這樣生成的 presigned URL 簽名才是正確的
    
    return presigned_url


def upload_bytes(
    data: bytes,
    object_key: str,
    *,
    bucket: Optional[str] = None,
    content_type: Optional[str] = None,
) -> None:
    fileobj = BytesIO(data)
    upload_fileobj(
        fileobj,
        len(data),
        object_key,
        bucket=bucket,
        content_type=content_type,
    )


def upload_fileobj(
    fileobj: BinaryIO,
    length: int,
    object_key: str,
    *,
    bucket: Optional[str] = None,
    content_type: Optional[str] = None,
) -> None:
    normalized_key = normalize_s3_key(object_key)
    extra_args = {}
    if content_type:
        extra_args["ContentType"] = content_type

    _s3_internal.upload_fileobj(
        fileobj,
        bucket or MINIO_BUCKET,
        normalized_key,
        ExtraArgs=extra_args or None,
    )


def delete_object(object_key: str, *, bucket: Optional[str] = None) -> None:
    normalized_key = normalize_s3_key(object_key)
    try:
        _s3_internal.delete_object(Bucket=bucket or MINIO_BUCKET, Key=normalized_key)
    except Exception as exc:
        # 靜默忽略不存在的物件
        if "NoSuchKey" not in str(exc):
            raise

