# 2-1-6 刪除當日 Vlog

# Mermaid
```mermaid
sequenceDiagram
  actor User
  participant Browser
  participant WebUIServer
  participant APIServer
  participant Postgres
  participant Minio

  User ->> Browser: 點選【刪除Vlog】
  Browser ->> Browser: 顯示刪除確認視窗

  alt 取消
    User ->> Browser: 點選【取消】
    Browser ->> Browser: 關閉確認視窗\n不做任何變更
  else 確認刪除
    User ->> Browser: 點選【確認】
    Browser ->> WebUIServer: DELETE /bff/v1/vlogs/{vlogId}\nAuthorization: Bearer jwt
    WebUIServer ->> APIServer: DELETE /api/v1/vlogs/{vlogId}

    APIServer ->> Postgres: SELECT vlog WHERE (id,user_id)
    Postgres -->> APIServer: vlog row / null

    alt vlog 不存在
      APIServer -->> WebUIServer: 404 {detail:"Vlog 不存在"}
      WebUIServer -->> Browser: 404 ...
      Browser ->> Browser: 顯示錯誤
    else vlog 存在
      opt best-effort 刪除 MinIO 影片物件
        APIServer ->> Minio: remove_object(bucket, vlog.s3_key)
        alt MinIO 刪除失敗
          Minio -->> APIServer: error
          APIServer ->> APIServer: 記錄 log\n不中斷刪除流程
        else MinIO 刪除成功
          Minio -->> APIServer: ok
        end
      end

      APIServer ->> Postgres: DELETE vlog（vlog_segments CASCADE）
      Postgres -->> APIServer: commit ok
      APIServer -->> WebUIServer: 200 {ok:true}
      WebUIServer -->> Browser: 200 {ok:true}
      Browser ->> Browser: 重新載入該日 Vlog 狀態
    end
  end
```

## Mermaid 備註
- API：`DELETE /bff/v1/vlogs/{vlogId}`。\n- 後端實作：先 best-effort 刪除 MinIO 物件，再刪除 `vlogs` 記錄；`vlog_segments` 依 DB 關聯 CASCADE 一併刪除。\n- 缺少的關鍵資訊：是否也刪除縮圖物件 `thumbnail_s3_key`（程式碼片段顯示主要刪 `s3_key`）；本圖僅畫出影片刪除（假設）。\n+

