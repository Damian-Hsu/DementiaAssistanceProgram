# Nginx 反向代理配置說明

## 概述

本配置使用 Nginx 作為反向代理，將所有服務統一通過 80/443 端口對外提供，同時支援分散式部署。

## 路由規則

| 路徑 | 目標服務 | 說明 |
|------|---------|------|
| `/api/v1/*` | APIServer (30000) | API 服務 |
| `/webrtc/*` | MediaMTX WebRTC (8889) | WebRTC 串流 |
| `/hls/*` | MediaMTX HLS (8888) | HLS 串流 |
| `/` | WebUIServer (30100) | Web 前端介面 |
| `:8554` (TCP) | MediaMTX RTSP (8554) | RTSP 串流（TCP 協議，獨立端口） |

## 重要說明

### RTSP 協議限制

RTSP 是 TCP 協議，**無法通過 HTTP 路徑代理**，必須使用獨立的 TCP 端口。因此：

- RTSP 使用端口 **8554**（通過 Nginx stream 模組代理）
- RTSP URL 格式：`rtsp://<domain>:8554/<path>?token=xxx`
- 無法使用 `rtsp://<domain>/rtsp/...` 這種 HTTP 路徑格式

### 其他服務

- **WebRTC**: 通過 `/webrtc/` 路徑訪問
- **HLS**: 通過 `/hls/` 路徑訪問
- **API**: 通過 `/api/v1/` 路徑訪問
- **WebUI**: 通過 `/` 根路徑訪問

## 環境變數配置

在 `.env` 文件中配置各服務的公開網域：

```bash
# API Server 公開網域
API_PUBLIC_DOMAIN=192.168.191.20
API_PUBLIC_SCHEME=http
API_PUBLIC_PORT=80

# WebUI Server 公開網域
WEBUI_PUBLIC_DOMAIN=192.168.191.20
WEBUI_PUBLIC_SCHEME=http
WEBUI_PUBLIC_PORT=80

# MediaMTX RTSP 公開網域（必須使用獨立 TCP 端口）
RTSP_PUBLIC_DOMAIN=192.168.191.20
RTSP_PUBLIC_SCHEME=rtsp
RTSP_PUBLIC_PORT=8554

# MediaMTX HLS 公開網域
HLS_PUBLIC_DOMAIN=192.168.191.20
HLS_PUBLIC_SCHEME=http
HLS_PUBLIC_PORT=80

# MediaMTX WebRTC 公開網域
WEBRTC_PUBLIC_DOMAIN=192.168.191.20
WEBRTC_PUBLIC_SCHEME=http
WEBRTC_PUBLIC_PORT=80

# MinIO 公開網域（用於生成 presigned URL）
MINIO_PUBLIC_DOMAIN=192.168.191.20
MINIO_PUBLIC_SCHEME=http
MINIO_PUBLIC_PORT=80
```

## 自動偵測

如果環境變數未設定，系統會自動從 Request Host header 偵測網域：

- 使用者訪問 `http://192.168.191.20` → 系統生成 `http://192.168.191.20/...`
- 使用者訪問 `https://app.lifelog.ai` → 系統生成 `https://app.lifelog.ai/...`

## 分散式部署

每個服務的網域可以獨立設定，支援分散式部署：

```bash
# 範例：分散式部署
API_PUBLIC_DOMAIN=api.lifelog.ai
WEBUI_PUBLIC_DOMAIN=app.lifelog.ai
RTSP_PUBLIC_DOMAIN=stream.lifelog.ai
```

## 啟動服務

```bash
# 啟動所有服務（包含 Nginx）
docker compose -f deploy/docker-compose.yml up -d

# 查看 Nginx 日誌
docker logs nginx_proxy -f

# 測試健康檢查
curl http://localhost/healthz
```

## HTTPS 配置（可選）

如需啟用 HTTPS，請：

1. 準備 SSL 證書（`cert.pem` 和 `key.pem`）
2. 取消註解 `nginx.conf` 中的 HTTPS server 區塊
3. 更新證書路徑
4. 更新環境變數中的 `*_PUBLIC_SCHEME=https` 和 `*_PUBLIC_PORT=443`

## 故障排除

### 檢查 Nginx 配置

```bash
docker exec nginx_proxy nginx -t
```

### 重新載入配置

```bash
docker exec nginx_proxy nginx -s reload
```

### 查看錯誤日誌

```bash
docker logs nginx_proxy
tail -f datas/logs/nginx/error.log
```

