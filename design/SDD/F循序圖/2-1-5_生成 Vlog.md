# 2-1-5 生成 Vlog

# Mermaid
```mermaid
sequenceDiagram
  actor User
  participant Browser
  participant WebUIServer
  participant APIServer
  participant Postgres
  participant Redis
  participant ComputeServer
  participant Minio

  User ->> Browser: 在首頁點選【生成Vlog】
  Browser ->> Browser: 開啟「事件選擇」視窗

  Browser ->> WebUIServer: GET /bff/v1/vlogs/events/{date}\nAuthorization: Bearer jwt
  WebUIServer ->> APIServer: GET /api/v1/vlogs/events/{date}
  APIServer ->> Postgres: SELECT events by date & user_id
  Postgres -->> APIServer: events[]
  APIServer -->> WebUIServer: 200 {events:[...]}
  WebUIServer -->> Browser: 200 {events:[...]}

  opt AI 推薦勾選（見 2-1-5-2）
    User ->> Browser: 點選【AI推薦】
    Browser ->> WebUIServer: POST /bff/v1/vlogs/ai-select\n{date, limit, summary_text?}
    WebUIServer ->> APIServer: POST /api/v1/vlogs/ai-select
    APIServer ->> Redis: enqueue tasks.suggest_vlog_highlights (async)
    Redis -->> ComputeServer: deliver task (async)
    ComputeServer ->> Postgres: UPDATE inference_jobs progress/status (async)
    APIServer -->> WebUIServer: 200 {selected_event_ids}
    WebUIServer -->> Browser: 200 ...
    Browser ->> Browser: 自動勾選推薦事件
  end

  User ->> Browser: 手動勾選/調整事件清單
  Browser ->> Browser: 檢查最少事件數量門檻\n達標後允許【下一步】
  User ->> Browser: 點選【下一步】
  Browser ->> Browser: 開啟「Vlog 參數設定」視窗

  opt 載入音樂清單（見 2-1-5-5）
    Browser ->> WebUIServer: GET /bff/v1/music?skip=0&limit=100
    WebUIServer ->> APIServer: GET /api/v1/music?...
    APIServer ->> Postgres: SELECT music list
    Postgres -->> APIServer: music[]
    APIServer -->> WebUIServer: 200 ...
    WebUIServer -->> Browser: 200 ...
  end

  User ->> Browser: 設定解析度/最大長度/音樂片段\n點選【送出生成】
  Browser ->> WebUIServer: POST /bff/v1/vlogs\n{target_date,event_ids,resolution,max_duration,music_*}\nAuthorization: Bearer jwt
  WebUIServer ->> APIServer: POST /api/v1/vlogs

  APIServer ->> Postgres: 驗證 events 屬於 user\n且日期一致
  APIServer ->> Postgres: INSERT vlogs(status=pending)\n+ INSERT vlog_segments
  APIServer ->> Postgres: INSERT inference_jobs(type=vlog_generation,status=pending)
  Postgres -->> APIServer: commit ok (vlog_id, job_id)

  APIServer ->> Redis: enqueue tasks.generate_vlog (async)
  APIServer -->> WebUIServer: 201 {vlog_id, job_id, status=pending}
  WebUIServer -->> Browser: 201 ...
  Browser ->> Browser: 顯示生成中\n並開始輪詢 Vlog 狀態（見 2-1-4）

  rect rgba(200,200,200,0.2)
    note over Redis,ComputeServer: 背景任務 (async)
    Redis -->> ComputeServer: tasks.generate_vlog
    ComputeServer ->> APIServer: POST /api/v1/vlogs/internal/segments\n(X-API-Key)\n取得片段資訊 (async)
    APIServer ->> Postgres: SELECT vlog_segments/recordings
    Postgres -->> APIServer: segments info
    APIServer -->> ComputeServer: 200 segments info
    ComputeServer ->> Minio: 下載片段/上傳完成影片與縮圖 (async)
    ComputeServer ->> APIServer: PATCH /api/v1/vlogs/internal/{vlog_id}/status\n(progress/status/s3_key/thumbnail_s3_key)\n(X-API-Key)
    APIServer ->> Postgres: UPDATE vlogs + inference_jobs progress/status
    Postgres -->> APIServer: ok
    APIServer -->> ComputeServer: 200 ok
  end
```

## Mermaid 備註
- 前端主流程：事件選擇（載入/AI推薦/手動）→ 參數設定（含音樂）→ 送出生成。\n- 後端主流程：`POST /vlogs` 建立 `vlogs/vlog_segments/inference_jobs`，再透過 Celery enqueue 到 **Redis**，由 **ComputeServer** worker 生成並回寫狀態。\n- 缺少的關鍵資訊：ComputeServer 實際下載來源（錄影片段在 MinIO 的 bucket/key 結構）與 FFmpeg 處理細節在此圖以「下載片段/上傳影片」抽象表示（假設）。\n+

