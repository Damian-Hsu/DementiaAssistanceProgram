#!/bin/sh
set -e

# 等待 MinIO 起來
until mc alias set local http://minio:9000 $MINIO_ROOT_USER $MINIO_ROOT_PASSWORD; do
  echo "waiting for minio..."
  sleep 2
done

# 建立 bucket (已存在就跳過)    
mc mb -p local/media-bucket || true
mc anonymous set none local/media-bucket || true

echo "Bucket 'media-bucket' is created and configured."
