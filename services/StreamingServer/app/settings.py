# -*- coding: utf-8 -*-
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

class _Settings:
    # Streaming（原本就有）
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    mediamtx_rtsp_base: str = os.getenv("MEDIAMTX_RTSP_BASE", "rtsp://mediamtx:8554")
    segment_seconds: int = int(os.getenv("SEGMENT_SECONDS", "30"))
    align_first_cut: bool = os.getenv("ALIGN_FIRST_CUT", "true").lower() == "true"
    record_root: str = os.getenv("RECORD_ROOT", "/recordings")
    log_dir: str = os.getenv("LOG_DIR", "/var/log/streaming")
    internal_token: str = os.getenv("INTERNAL_TOKEN", "")

    # Uploader（原本就有）
    # 內部連接使用 Docker 服務名稱和內部端口
    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "http://minio:9000")
    minio_access_key: str = os.getenv("MINIO_ROOT_USER", "")
    minio_secret_key: str = os.getenv("MINIO_ROOT_PASSWORD", "")
    minio_bucket: str = os.getenv("MINIO_BUCKET", "media-bucket")
    uploader_db: str = os.getenv("UPLOADER_DB", "/recordings/uploader.db")  # 使用 recordings volume，避免額外掛載

    job_api_base: str = os.getenv("JOB_API_BASE", "http://api:30000/api/v1")
    job_api_key: str = os.getenv("JOB_API_KEY", "")  # 具 uploader scope 的 key


    # === 新增：RTSP 與 Token 設定（用於自動組 RTSP URL 與簽發短效 token） ===
    # 注意端口區分：
    # - mediamtx_rtsp_base: 使用容器內部端口 8554（Docker 網絡內通信）
    # - rtsp_port: 外部端口（僅用於參考，StreamingServer 不需要直接使用）
    # Docker 端口映射：外部 8554 → 容器內部 8554（通過 Nginx）
    rtsp_public_host: str = os.getenv("RTSP_PUBLIC_HOST", "")  # 留空，使用環境變數或自動偵測
    rtsp_port: int = int(os.getenv("RTSP_PORT", "8554"))  # 預設使用 Nginx 代理的端口

    stream_jwt_secret: str = os.getenv("STREAM_JWT_SECRET", "replace-me")  # 務必改成強隨機字串
    stream_jwt_alg: str = os.getenv("STREAM_JWT_ALG", "HS256")
    stream_token_ttl_seconds: int = int(os.getenv("STREAM_TOKEN_TTL_SECONDS", "180"))  # 2~5 分鐘建議

settings = _Settings()

# 建立必要目錄
Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
Path(settings.record_root).mkdir(parents=True, exist_ok=True)
