# LifeLog.ai 開發手冊

## 📚 文件導航

- **技術規格**: [spec.md](./spec.md) - 完整的系統架構與 API 設計
- **任務清單**: [todolist.md](./todolist.md) - 開發任務與進度追蹤
- **開發報告**: [report.md](./report.md) - 開發過程記錄與問題解決

---

## 🚀 快速開始

### 環境需求

- **作業系統**: Windows 11
- **Python**: 3.12.11
- **Docker**: Docker Desktop for Windows
- **GPU**: NVIDIA GPU (可選，用於加速 AI 模型推理)

---

## 🐳 Docker 啟動與管理

### 方法 1：使用 restart.bat（推薦）

**功能**: 自動停止、重建並啟動所有服務

```bash
# 在專案根目錄開啟終端機（PowerShell 或 CMD）
.\restart.bat
```

**執行內容**:
```batch
docker compose -f deploy/docker-compose.yml down
docker compose -f deploy/docker-compose.yml up -d --build
```

**說明**:
- `down`: 停止並移除所有容器
- `up -d`: 在背景模式啟動服務
- `--build`: 重新建置映像檔（確保使用最新的程式碼）

**適用情境**:
- ✅ 更新程式碼後重啟
- ✅ 遇到服務異常需要完全重啟
- ✅ 修改 Dockerfile 或 docker-compose.yml 後

---

### 方法 2：手動啟動（開發模式）

#### 首次啟動

```bash
# 1. 進入專案根目錄
cd D:\School\畢業專題\demo\DementiaAssistanceProgram

# 2. 啟動所有服務（前景模式，可看到即時日誌）
docker compose -f deploy/docker-compose.yml up
```

#### 背景模式啟動

```bash
# 在背景啟動（不佔用終端機）
docker compose -f deploy/docker-compose.yml up -d
```

#### 停止服務

```bash
# 停止所有服務（保留容器）
docker compose -f deploy/docker-compose.yml stop

# 停止並移除容器
docker compose -f deploy/docker-compose.yml down

# 停止並移除容器、網路、映像檔
docker compose -f deploy/docker-compose.yml down --rmi all
```

---

### 方法 3：單獨管理服務

#### 查看服務狀態

```bash
# 查看所有服務狀態
docker compose -f deploy/docker-compose.yml ps

# 查看服務日誌
docker compose -f deploy/docker-compose.yml logs

# 查看特定服務日誌（例如：api）
docker compose -f deploy/docker-compose.yml logs -f api

# 查看最近 100 行日誌
docker compose -f deploy/docker-compose.yml logs --tail=100
```

#### 重啟單一服務

```bash
# 重啟 APIServer
docker compose -f deploy/docker-compose.yml restart api

# 重啟 ComputeServer
docker compose -f deploy/docker-compose.yml restart compute

# 重啟 StreamingServer
docker compose -f deploy/docker-compose.yml restart streaming
```

#### 重建單一服務

```bash
# 停止、重建並啟動 APIServer
docker compose -f deploy/docker-compose.yml up -d --build api

# 停止、重建並啟動 ComputeServer
docker compose -f deploy/docker-compose.yml up -d --build compute
```

---

## 🔍 服務架構

### 服務列表

| 服務名稱 | 容器名稱 | 外部端口 | 內部端口 | 功能 |
| --- | --- | --- | --- | --- |
| **postgres** | demo_postgres | 30700 | 5432 | PostgreSQL 資料庫 |
| **redis** | demo_redis | 30600 | 6379 | Redis 快取與任務佇列 |
| **minio** | demo_minio | 30300, 30301 | 9000, 9001 | MinIO 物件儲存 |
| **mediamtx** | mediamtx | 30201, 30202, 30204 | 8554, 8888, 8889 | RTSP 串流路由器 |
| **api** | api_server | 30000 | 30000 | API Server (FastAPI) |
| **compute** | compute_server | - | - | Compute Server (Celery，不公開外網) |
| **streaming** | streaming_server | 30500 | 30500 | Streaming Server (FFmpeg) |
| **webui** | webui_server | 30100 | 30100 | Web UI Server |

### 服務依賴關係

```
postgres  ─┐
redis     ─┼─→ api ──→ compute
minio     ─┤           │
mediamtx  ─┴─→ streaming ──┘
```

---

## 🛠️ 開發工作流程

### 1. 啟動開發環境

```bash
# 方式 A: 使用 restart.bat（最簡單）
.\restart.bat

# 方式 B: 手動啟動（可看日誌）
docker compose -f deploy/docker-compose.yml up
```

### 2. 驗證服務健康狀態

```bash
# 檢查所有服務是否啟動
docker compose -f deploy/docker-compose.yml ps

# 測試 API Server
curl http://localhost:8000/healthz

# 測試 Streaming Server
curl http://localhost:9090/healthz

# 查看 PostgreSQL 連線
docker exec -it demo_postgres psql -U <DB_USER> -d <DB_NAME>

# 查看 Redis 連線
docker exec -it demo_redis redis-cli ping
```

### 3. 開發與測試循環

```bash
# 1. 修改程式碼
# 2. 重啟對應服務
docker compose -f deploy/docker-compose.yml restart <service_name>

# 3. 查看日誌
docker compose -f deploy/docker-compose.yml logs -f <service_name>

# 4. 測試功能
# 使用瀏覽器或 Postman 測試 API
```

### 4. 前端開發

```bash
# 前端檔案位置
view.html               # 主要測試頁面
view_recordings.html    # 錄影檢視頁面

# 直接用瀏覽器開啟檔案或透過 Live Server
```

### 5. 資料庫管理

```bash
# 進入 PostgreSQL
docker exec -it demo_postgres psql -U <DB_USER> -d <DB_NAME>

# 查看所有表格
\dt

# 查看特定表格結構
\d users
\d recordings
\d events

# 執行 SQL 查詢
SELECT * FROM users LIMIT 10;

# 退出
\q
```

---

## 🧪 測試流程

### 1. 完整端到端測試

```bash
# 1. 啟動系統
.\restart.bat

# 2. 等待所有服務啟動（約 30-60 秒）
docker compose -f deploy/docker-compose.yml logs -f

# 3. 開啟測試頁面
# 瀏覽器訪問：file:///D:/School/畢業專題/demo/DementiaAssistanceProgram/view.html
# 或使用：http://localhost:8000（如果有設定 static files）

# 4. 執行 Demo 流程
# - 登入系統
# - 取得攝影機連線連結
# - 使用 ip_camera_sim.py 推流
# - 查看事件生成
# - 測試自然語言查詢
# - 建立 Vlog
```

### 2. IP Camera 模擬推流

```bash
# 使用 Python 腳本模擬 IP Camera
python ip_camera_sim.py

# 輸入剛才從系統取得的 RTSP URL
# 例如：rtsp://localhost:8554/camera1?token=xxxxx
```

### 3. API 測試

```bash
# 測試 API 健康檢查
curl http://localhost:8000/healthz

# 測試登入
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=yourpassword"

# 測試事件查詢（需要 JWT Token）
curl http://localhost:8000/api/v1/events \
  -H "Authorization: Bearer <your_token>"
```

---

## 🔧 常見問題排解

### 問題 1: Docker Compose 啟動失敗

**症狀**: `docker compose up` 執行後服務無法啟動

**可能原因與解決方案**:

```bash
# 1. 檢查 Docker Desktop 是否正在運行
# 開啟 Docker Desktop 應用程式

# 2. 檢查端口是否被佔用
netstat -ano | findstr "8000"
netstat -ano | findstr "5432"
netstat -ano | findstr "6379"
netstat -ano | findstr "9000"

# 3. 清理舊容器和網路
docker compose -f deploy/docker-compose.yml down
docker network prune
docker volume prune

# 4. 重新啟動
.\restart.bat
```

---

### 問題 2: 服務健康檢查失敗

**症狀**: 容器啟動但 healthcheck 一直 unhealthy

**解決方案**:

```bash
# 1. 查看服務日誌
docker compose -f deploy/docker-compose.yml logs <service_name>

# 2. 進入容器檢查
docker exec -it <container_name> /bin/bash

# 3. 檢查環境變數
docker exec -it <container_name> env

# 4. 手動測試健康檢查命令
docker exec -it api_server curl http://localhost:8000/healthz
```

---

### 問題 3: ComputeServer 任務處理失敗

**症狀**: 影片上傳後沒有生成事件

**解決方案**:

```bash
# 1. 查看 ComputeServer 日誌
docker compose -f deploy/docker-compose.yml logs -f compute

# 2. 檢查 Redis 連線
docker exec -it demo_redis redis-cli
> PING
> KEYS *

# 3. 檢查 Celery Worker 狀態
docker exec -it compute_server celery -A app.main inspect active

# 4. 檢查 GPU 是否可用（如有）
docker exec -it compute_server python -c "import torch; print(torch.cuda.is_available())"

# 5. 手動重試任務
# 透過 API 重新提交任務或重啟 ComputeServer
docker compose -f deploy/docker-compose.yml restart compute
```

---

### 問題 4: MinIO 連線失敗

**症狀**: 影片無法上傳或下載

**解決方案**:

```bash
# 1. 檢查 MinIO 服務狀態
docker compose -f deploy/docker-compose.yml logs minio

# 2. 訪問 MinIO Console
# 瀏覽器開啟：http://localhost:9001
# 使用 .env 中的 MINIO_ROOT_USER 和 MINIO_ROOT_PASSWORD 登入

# 3. 檢查 Bucket 是否建立
# 在 MinIO Console 中查看 buckets

# 4. 重新初始化 MinIO
docker compose -f deploy/docker-compose.yml restart minio minio-init
```

---

### 問題 5: MediaMTX RTSP 推流失敗

**症狀**: IP Camera 無法連線到 RTSP 服務

**解決方案**:

```bash
# 1. 檢查 MediaMTX 日誌
docker compose -f deploy/docker-compose.yml logs -f mediamtx

# 2. 測試 RTSP 端口
# Windows PowerShell
Test-NetConnection -ComputerName localhost -Port 8554

# 3. 檢查 Token 是否有效
# 確認從 API 取得的 RTSP URL 包含有效的 token

# 4. 重啟 MediaMTX
docker compose -f deploy/docker-compose.yml restart mediamtx
```

---

## 📝 開發注意事項

### 1. 環境變數管理

```bash
# 環境變數檔案位置
deploy/.env

# 重要變數（請勿提交到 Git）
DB_SUPERUSER=<your_db_user>
DB_SUPERPASS=<your_db_password>
MINIO_ROOT_USER=<your_minio_user>
MINIO_ROOT_PASSWORD=<your_minio_password>
GOOGLE_API_KEY=<your_google_api_key>
```

**注意**: 
- ⚠️ `.env` 檔案包含敏感資訊，不應提交到版本控制
- ⚠️ 確保 `.gitignore` 已包含 `.env`

---

### 2. 日誌管理

```bash
# 日誌儲存位置
datas/logs/
├── api/          # API Server 日誌
├── compute/      # Compute Server 日誌
└── streaming/    # Streaming Server 日誌

# 查看即時日誌
tail -f datas/logs/api/*.log
tail -f datas/logs/compute/*.log

# 清理舊日誌（小心操作）
rm -rf datas/logs/api/*
rm -rf datas/logs/compute/*
rm -rf datas/logs/streaming/*
```

---

### 3. 資料持久化

```bash
# 資料儲存位置
datas/
├── postgres_data/        # PostgreSQL 資料
├── minio_data/          # MinIO 物件儲存
│   ├── data1/
│   ├── data2/
│   ├── data3/
│   └── data4/
├── streaming/           # 串流錄影檔案
│   └── recordings/
└── compute/            # AI 模型快取
    └── adapters/
```

**備份建議**:
- 📦 定期備份 `datas/postgres_data/`
- 📦 定期備份 `datas/minio_data/`
- 📦 重要錄影可匯出到外部儲存

---

### 4. 程式碼修改後的更新流程

#### 修改 APIServer 程式碼

```bash
# 1. 修改 services/APIServer/app/*.py
# 2. 重建並重啟服務
docker compose -f deploy/docker-compose.yml up -d --build api

# 3. 驗證
curl http://localhost:8000/healthz
```

#### 修改 ComputeServer 程式碼

```bash
# 1. 修改 services/ComputeServer/app/*.py
# 2. 重建並重啟服務
docker compose -f deploy/docker-compose.yml up -d --build compute

# 3. 查看日誌確認載入成功
docker compose -f deploy/docker-compose.yml logs -f compute
```

#### 修改 StreamingServer 程式碼

```bash
# 1. 修改 services/StreamingServer/app/*.py
# 2. 重建並重啟服務
docker compose -f deploy/docker-compose.yml up -d --build streaming

# 3. 驗證
curl http://localhost:9090/healthz
```

#### 修改資料庫 Schema

```bash
# 1. 建立 migration 腳本
# 在 deploy/postgres/init-scripts/ 新增 SQL 檔案

# 2. 完全重啟（會執行新的 migration）
docker compose -f deploy/docker-compose.yml down
docker volume rm demo_postgres_data  # ⚠️ 會刪除資料庫資料
docker compose -f deploy/docker-compose.yml up -d

# 3. 或手動執行 SQL
docker exec -it demo_postgres psql -U <DB_USER> -d <DB_NAME> -f /docker-entrypoint-initdb.d/new_migration.sql
```

---

## 🚢 部署檢查清單

### Demo 前準備

- [ ] **環境檢查**
  - [ ] Docker Desktop 正在運行
  - [ ] 所有服務健康檢查通過
  - [ ] 網路連線穩定

- [ ] **資料準備**
  - [ ] 測試帳號已建立
  - [ ] 測試影片已準備（或使用 ip_camera_sim.py）
  - [ ] MinIO Bucket 已建立

- [ ] **功能測試**
  - [ ] 登入功能正常
  - [ ] 攝影機連線正常
  - [ ] 錄影功能正常
  - [ ] 事件生成正常
  - [ ] 自然語言查詢正常
  - [ ] Vlog 生成正常（如已實作）
  - [ ] 每日日誌正常（如已實作）

- [ ] **備用方案**
  - [ ] 預錄 Demo 影片
  - [ ] 預先生成測試資料
  - [ ] 簡報準備完成
  - [ ] 備用網路方案

---

## 📚 參考資源

### 官方文件
- [Docker Compose 文件](https://docs.docker.com/compose/)
- [FastAPI 文件](https://fastapi.tiangolo.com/)
- [Celery 文件](https://docs.celeryq.dev/)
- [PostgreSQL 文件](https://www.postgresql.org/docs/)
- [Redis 文件](https://redis.io/docs/)
- [MinIO 文件](https://min.io/docs/)
- [MediaMTX 文件](https://github.com/bluenviron/mediamtx)

### 專案文件
- [技術規格 (spec.md)](./spec.md)
- [任務清單 (todolist.md)](./todolist.md)
- [開發報告 (report.md)](./report.md)

### 開發工具
- [Postman](https://www.postman.com/) - API 測試
- [DBeaver](https://dbeaver.io/) - 資料庫管理
- [Redis Desktop Manager](https://resp.app/) - Redis 管理

---

## 🆘 尋求協助

### 常用指令速查

```bash
# 快速重啟（最常用）
.\restart.bat

# 查看所有服務狀態
docker compose -f deploy/docker-compose.yml ps

# 查看特定服務日誌
docker compose -f deploy/docker-compose.yml logs -f <service_name>

# 重啟單一服務
docker compose -f deploy/docker-compose.yml restart <service_name>

# 完全清理並重新開始
docker compose -f deploy/docker-compose.yml down -v
.\restart.bat

# 進入容器內部 Debug
docker exec -it <container_name> /bin/bash
```

### 問題回報

如果遇到問題，請記錄以下資訊：

1. **錯誤訊息**: 完整的錯誤日誌
2. **操作步驟**: 重現問題的步驟
3. **環境資訊**: OS、Docker 版本、服務狀態
4. **日誌**: 相關服務的日誌檔案

---

**最後更新**: 2025-10-20  
**版本**: v1.0  
**維護者**: LifeLog.ai 開發團隊

