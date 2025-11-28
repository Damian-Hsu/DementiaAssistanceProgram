from __future__ import annotations

import os
from io import BytesIO
from typing import Optional, BinaryIO

import boto3
from botocore.config import Config


MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
MINIO_PUBLIC_ENDPOINT = os.getenv("MINIO_PUBLIC_ENDPOINT", "http://localhost:30300")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "media-bucket")
S3_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", os.getenv("S3_ACCESS_KEY", "minioadmin"))
S3_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", os.getenv("S3_SECRET_KEY", "minioadmin"))
S3_REGION = os.getenv("AWS_REGION", "us-east-1")

_s3_internal = boto3.client(
    "s3",
    endpoint_url=MINIO_ENDPOINT,
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    region_name=S3_REGION,
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)

_s3_public = None


def _get_public_client():
    global _s3_public
    if _s3_public is None:
        _s3_public = boto3.client(
            "s3",
            endpoint_url=MINIO_PUBLIC_ENDPOINT,
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

    if MINIO_PUBLIC_ENDPOINT and MINIO_PUBLIC_ENDPOINT != MINIO_ENDPOINT:
        client = _get_public_client()
    else:
        client = _s3_internal

    return client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=int(ttl),
    )


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

