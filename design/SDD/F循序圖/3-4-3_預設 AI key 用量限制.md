# 3-4-3 預設 AI key 用量限制

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

  Browser ->> WebUIServer: GET /bff/v1/admin/settings/default-ai-key-limits
  Note over Browser,WebUIServer: Authorization: Bearer jwt
  WebUIServer ->> APIServer: GET /api/v1/admin/settings/default-ai-key-limits
  APIServer ->> Postgres: SELECT settings(default_ai_key_limits)
  APIServer -->> WebUIServer: 200 {rpm, rpd}
  WebUIServer -->> Browser: 200
  Browser ->> Browser: 填入 RPM/RPD

  Admin ->> Browser: 輸入【RPM】與【RPD】
  Admin ->> Browser: 點選【儲存設定】

  alt RPM/RPD 欄位為空
    Browser ->> Browser: 不更新（保留既有設定）
  else 有值
    Browser ->> WebUIServer: POST /bff/v1/admin/settings/default-ai-key-limits
    Note over Browser,WebUIServer: body: {rpm, rpd}
    WebUIServer ->> APIServer: POST /api/v1/admin/settings/default-ai-key-limits

    alt 超出範圍（rpm 1~300 / rpd 1~10000）
      APIServer -->> WebUIServer: 400 {detail}
      WebUIServer -->> Browser: 400
      Browser ->> Browser: 顯示錯誤提示
    else 更新成功
      APIServer ->> Postgres: UPSERT settings.key=default_ai_key_limits
      Postgres -->> APIServer: commit
      APIServer -->> WebUIServer: 200 {rpm, rpd}
      WebUIServer -->> Browser: 200
      Browser ->> Browser: 顯示成功提示
    end
  end
```

## Mermaid 備註
- API：`GET/POST /bff/v1/admin/settings/default-ai-key-limits`。
- 寫入位置：`settings.key = default_ai_key_limits`（value 為 JSON：`{"rpm":10,"rpd":20}`）。
- 套用時機：只對「使用系統預設 API Key」的使用者套用（Chat 端會用 in-memory rate limiter 檢查）。
