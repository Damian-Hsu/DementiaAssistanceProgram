# 服務端口映射配置

本文檔記錄所有服務的端口映射配置。

## 端口映射表

| 服務 | 外部端口 | 內部端口 | 說明 |
|------|---------|---------|------|
| **API Service** | 30000 | 30000 | API 服務 |
| **WebUI Service** | 30100 | 30100 | 前端服務 |
| **MediaMTX** | | | |
| - RTSP | 30201 | 8554 | RTSP 推流/拉流 |
| - HLS | 30202 | 8888 | HLS 播放 |
| - WebRTC | 30204 | 8889 | WebRTC 播放 |
| **MinIO** | | | |
| - API | 30300 | 9000 | MinIO API |
| - Console | 30301 | 9001 | MinIO 管理控制台 |
| **Compute Service** | - | - | 不公開外網（30400 保留） |
| **Streaming Service** | 30500 | 30500 | 串流服務 |
| **Redis** | 30600 | 6379 | Redis 緩存（內部使用） |
| **PostgreSQL** | 30700 | 5432 | 資料庫（內部使用） |

## 配置位置

- **docker-compose.yml**: 端口映射配置
- **.env**: 環境變數配置（內部端口）
- **各服務配置**: 服務內部端口配置

## 注意事項

1. **內部通信**：Docker 網絡內的服務應使用服務名稱和內部端口
   - 例如：`http://api:30000`、`rtsp://mediamtx:8554`

2. **外部訪問**：外部客戶端應使用外部端口
   - 例如：`http://localhost:30000`、`rtsp://localhost:30201`

3. **MinIO**：
   - 內部使用：`http://minio:9000`
   - 外部訪問：`http://localhost:30300`（API）、`http://localhost:30301`（Console）

4. **MediaMTX**：
   - 內部使用：`rtsp://mediamtx:8554`、`http://mediamtx:8888`、`http://mediamtx:8889`
   - 外部訪問：`rtsp://localhost:30201`、`http://localhost:30202`、`http://localhost:30204`

