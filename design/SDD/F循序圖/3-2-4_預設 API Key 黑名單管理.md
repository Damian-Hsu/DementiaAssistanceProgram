# 3-2-4 預設 API Key 黑名單管理

# Mermaid
```mermaid
sequenceDiagram
  actor Admin
  participant Browser
  participant WebUIServer
  participant APIServer
  participant Postgres

  Admin ->> Browser: 在詳情視窗切換【黑名單】
  opt 加入黑名單
    Admin ->> Browser: 輸入【原因】(可空)
    Admin ->> Browser: 點選【儲存】

    Browser ->> WebUIServer: POST /bff/v1/admin/blacklist
    Note over Browser,WebUIServer: body: {user_id, reason?}
    WebUIServer ->> APIServer: POST /api/v1/admin/blacklist

    alt 使用者不存在
      APIServer -->> WebUIServer: 404 {detail}
      WebUIServer -->> Browser: 404
      Browser ->> Browser: 顯示錯誤提示
    else 成功
      APIServer ->> Postgres: UPSERT api_key_blacklist (user_id, reason)
      Note over APIServer: 若已存在則更新 reason（idempotent）
      APIServer ->> Postgres: (best-effort) 將 users.settings.use_default_api_key 設為 false
      Postgres -->> APIServer: commit
      APIServer -->> WebUIServer: 200 BlacklistEntry
      WebUIServer -->> Browser: 200
      Browser ->> Browser: 更新列表狀態（is_blacklisted=true, use_default_api_key=false）
    end
  end

  opt 移除黑名單
    Admin ->> Browser: 取消勾選【黑名單】並點選【儲存】

    Browser ->> WebUIServer: DELETE /bff/v1/admin/blacklist/{user_id}
    WebUIServer ->> APIServer: DELETE /api/v1/admin/blacklist/{user_id}

    alt 使用者不在黑名單中
      APIServer -->> WebUIServer: 404 {detail:"使用者不在黑名單中"}
      WebUIServer -->> Browser: 404
      Browser ->> Browser: 顯示錯誤提示
    else 成功
      APIServer ->> Postgres: DELETE api_key_blacklist WHERE user_id
      Postgres -->> APIServer: commit
      APIServer -->> WebUIServer: 200 {message}
      WebUIServer -->> Browser: 200
      Browser ->> Browser: 更新列表狀態（is_blacklisted=false）
    end
  end
```

## Mermaid 備註
- 加入/更新原因：前端一律呼叫 `POST /admin/blacklist`；後端若已存在則視為更新 reason。
- 加入黑名單會同步：嘗試把該使用者 `users.settings.use_default_api_key` 改為 `false`，避免仍使用系統預設 key。
- 黑名單的意義：被列入者在使用者設定頁無法啟用「使用系統預設 API Key」（見 2-6-6）。
