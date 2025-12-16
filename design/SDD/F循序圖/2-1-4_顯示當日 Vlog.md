# 2-1-4 顯示當日 Vlog

# Mermaid
```mermaid
sequenceDiagram
  actor User
  participant Browser
  participant WebUIServer
  participant APIServer
  participant Postgres
  participant Minio

  User ->> Browser: 開啟首頁或切換日期
  Browser ->> WebUIServer: GET /bff/v1/vlogs/date/{date}\nAuthorization: Bearer jwt
  WebUIServer ->> APIServer: GET /api/v1/vlogs/date/{date}
  APIServer ->> Postgres: SELECT latest vlog by (user_id,target_date)
  Postgres -->> APIServer: vlog row / null

  alt 該日無 Vlog
    APIServer -->> WebUIServer: 404
    WebUIServer -->> Browser: 404
    Browser ->> Browser: 顯示「尚未生成」狀態
  else 有 Vlog
    APIServer -->> WebUIServer: 200 {id,status,progress,status_message,...}
    WebUIServer -->> Browser: 200 ...

    alt status == completed
      Browser ->> WebUIServer: GET /bff/v1/vlogs/{id}/thumbnail-url?ttl=3600
      WebUIServer ->> APIServer: GET /api/v1/vlogs/{id}/thumbnail-url
      APIServer ->> Minio: 產生 presigned URL (縮圖)
      Minio -->> APIServer: presigned URL
      APIServer -->> WebUIServer: 200 {url}
      WebUIServer -->> Browser: 200 {url}

      Browser ->> WebUIServer: GET /bff/v1/vlogs/{id}/url?ttl=3600
      WebUIServer ->> APIServer: GET /api/v1/vlogs/{id}/url
      APIServer ->> Minio: 產生 presigned URL (影片)
      Minio -->> APIServer: presigned URL
      APIServer -->> WebUIServer: 200 {url}
      WebUIServer -->> Browser: 200 {url}
      Browser ->> Browser: 顯示縮圖與播放按鈕
    else status == pending/processing
      Browser ->> Browser: 顯示 spinner + 進度條
      loop 輪詢狀態（假設：每 N 秒）
        Browser ->> WebUIServer: GET /bff/v1/vlogs/{id}\nAuthorization: Bearer jwt
        WebUIServer ->> APIServer: GET /api/v1/vlogs/{id}
        APIServer ->> Postgres: SELECT vlogs WHERE id & user_id
        Postgres -->> APIServer: vlog row
        APIServer -->> WebUIServer: 200 {status,progress,...}
        WebUIServer -->> Browser: 200 ...
      end
    else status == failed
      Browser ->> Browser: 顯示失敗訊息\n可刪除（見 2-1-6）
    end
  end
```

## Mermaid 備註
- API：`GET /bff/v1/vlogs/date/{date}`、輪詢 `GET /bff/v1/vlogs/{id}`；完成後用 `GET /bff/v1/vlogs/{id}/url`、`GET /bff/v1/vlogs/{id}/thumbnail-url`。\n- 播放/縮圖 URL：由後端產生 MinIO 預簽名 URL（`generate_presigned_url`）。\n- 缺少的關鍵資訊：輪詢間隔與停止條件由 `vlog.js` 控制；本圖以「每 N 秒」表示（假設）。\n+

