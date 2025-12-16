# 3-4-5 M2M API Key 管理

# Mermaid
```mermaid
sequenceDiagram
  actor Admin
  participant Browser
  participant WebUIServer
  participant APIServer
  participant Postgres

  Admin ->> Browser: 開啟【管理員設定】頁
  Browser ->> WebUIServer: GET /admin/settings
  WebUIServer -->> Browser: 200 admin_settings.html + admin_settings.js

  Browser ->> WebUIServer: GET /bff/v1/admin/api-keys
  Note over Browser,WebUIServer: Authorization: Bearer jwt
  WebUIServer ->> APIServer: GET /api/v1/admin/api-keys
  APIServer ->> Postgres: SELECT api_keys
  APIServer -->> WebUIServer: 200 [ApiKeyOut...]
  WebUIServer -->> Browser: 200
  Browser ->> Browser: 渲染 API Key 列表

  opt 建立 API Key
    Admin ->> Browser: 填寫名稱/擁有者ID/scopes/限制
    Admin ->> Browser: 送出【建立 API Key】
    Browser ->> WebUIServer: POST /bff/v1/admin/api-keys
    Note over Browser,WebUIServer: body: {name, owner_id, scopes, rate_limit_per_min?, quota_per_day?}
    WebUIServer ->> APIServer: POST /api/v1/admin/api-keys

    alt owner_id 不存在
      APIServer -->> WebUIServer: 404 {detail:"Owner user not found"}
      WebUIServer -->> Browser: 404
      Browser ->> Browser: 顯示錯誤提示
    else 成功
      APIServer ->> Postgres: INSERT api_keys (token_hash, scopes, limits)
      Postgres -->> APIServer: commit
      APIServer -->> WebUIServer: 201 {id, ..., token}
      WebUIServer -->> Browser: 201
      Browser ->> Browser: 顯示 token 並嘗試複製到剪貼簿
      Note over Browser: token 明碼只回傳一次
    end
  end

  opt 編輯 API Key（名稱/Scopes/限制）
    Admin ->> Browser: 點擊列表列 → 開啟編輯對話框 → 送出
    Browser ->> WebUIServer: PATCH /bff/v1/admin/api-keys/{key_id}
    WebUIServer ->> APIServer: PATCH /api/v1/admin/api-keys/{key_id}
    APIServer ->> Postgres: UPDATE api_keys
    APIServer -->> Browser: 200 ApiKeyOut
  end

  opt 旋轉 API Key
    Admin ->> Browser: 點選【旋轉】並確認
    Browser ->> WebUIServer: POST /bff/v1/admin/api-keys/{key_id}/rotate
    WebUIServer ->> APIServer: POST /api/v1/admin/api-keys/{key_id}/rotate
    APIServer ->> Postgres: UPDATE api_keys.token_hash（舊 token 立即失效）
    APIServer -->> Browser: 201 {id, ..., token}
    Browser ->> Browser: 顯示新 token 並嘗試複製
  end

  opt 停用（刪除按鈕以停用實作）
    Admin ->> Browser: 點選【刪除】並確認
    Browser ->> WebUIServer: PATCH /bff/v1/admin/api-keys/{key_id}
    Note over Browser,WebUIServer: body: {active:false}
    WebUIServer ->> APIServer: PATCH /api/v1/admin/api-keys/{key_id}
    APIServer ->> Postgres: UPDATE api_keys.active=false
    APIServer -->> Browser: 200 ApiKeyOut
  end
```

## Mermaid 備註
- API：
  - 列表：`GET /bff/v1/admin/api-keys`
  - 建立：`POST /bff/v1/admin/api-keys`
  - 更新：`PATCH /bff/v1/admin/api-keys/{key_id}`
  - 旋轉：`POST /bff/v1/admin/api-keys/{key_id}/rotate`
- token 明碼僅在「建立/旋轉」回傳一次；前端會提示並嘗試複製到剪貼簿。
- 前端的【刪除】目前是以 `active=false` 實作停用（後端未提供真正刪除端點）。
