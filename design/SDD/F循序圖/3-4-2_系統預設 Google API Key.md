# 3-4-2 系統預設 Google API Key

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

  Browser ->> WebUIServer: GET /bff/v1/admin/settings/default-google-api-key
  Note over Browser,WebUIServer: Authorization: Bearer jwt
  WebUIServer ->> APIServer: GET /api/v1/admin/settings/default-google-api-key
  APIServer ->> Postgres: SELECT settings(default_google_api_key)
  APIServer -->> WebUIServer: 200 {api_key:"********"}
  WebUIServer -->> Browser: 200
  Browser ->> Browser: 以 placeholder 顯示遮罩後的 key（不回填 input value）

  Admin ->> Browser: 輸入【系統預設 Google API Key】
  Admin ->> Browser: 點選【儲存設定】

  alt 輸入框為空
    Browser ->> Browser: 不更新（保留既有設定）
  else 有輸入
    Browser ->> WebUIServer: POST /bff/v1/admin/settings/default-google-api-key
    Note over Browser,WebUIServer: body: {api_key}
    WebUIServer ->> APIServer: POST /api/v1/admin/settings/default-google-api-key
    APIServer ->> Postgres: UPSERT settings.key=default_google_api_key
    Postgres -->> APIServer: commit
    APIServer -->> WebUIServer: 200 {api_key:<原始輸入>}
    WebUIServer -->> Browser: 200
    Browser ->> Browser: 清空 input（安全）並更新 placeholder
  end
```

## Mermaid 備註
- API：`GET/POST /bff/v1/admin/settings/default-google-api-key`。
- 顯示策略：GET 端點只回傳遮罩後的 key（前 8 + 後 8），避免明碼顯示。
- 寫入位置：`settings.key = default_google_api_key`（value 以 JSON 字串保存：`{"api_key": "..."}`）。
