# 2-2-4 取得 RTSP 推流 URL

# Mermaid
```mermaid
sequenceDiagram
  actor User
  participant Browser
  participant WebUIServer
  participant APIServer
  participant Postgres
  participant Mediamtx

  User ->> Browser: 點選【串流連結】
  Browser ->> WebUIServer: GET /bff/v1/camera/{id}/publish_rtsp_url?ttl=10800\nAuthorization: Bearer jwt
  WebUIServer ->> APIServer: GET /api/v1/camera/{id}/publish_rtsp_url?ttl=10800

  APIServer ->> Postgres: SELECT camera WHERE id
  Postgres -->> APIServer: camera row

  alt 權限不足/鏡頭未啟用
    APIServer -->> WebUIServer: 403/404
    WebUIServer -->> Browser: 403/404
    Browser ->> Browser: 顯示錯誤
  else 成功簽發推流 token
    APIServer ->> APIServer: issue JWT\n(aud=rtsp, action=publish, ver=token_version, ttl)
    APIServer -->> WebUIServer: 200 {publish_rtsp_url, expires_at}
    WebUIServer -->> Browser: 200 {publish_rtsp_url,...}
    Browser ->> Browser: 複製 publish_rtsp_url 到剪貼簿\n顯示成功/失敗提示
  end

  opt 外部推流端使用該 URL（不在元件清單，僅用 note 表示）
    note over Mediamtx: 外部攝影機/OBS 以 publish_rtsp_url 推流到 Mediamtx
    Mediamtx ->> APIServer: HTTP auth 回打 /api/v1/m2m/check-stream-pwd\n(action=publish, protocol=rtsp, path, query.token)
    alt token 驗證成功
      APIServer -->> Mediamtx: 200 OK
    else token 無效/過期/路徑不符
      APIServer -->> Mediamtx: 401 Unauthorized
    end
  end
```

## Mermaid 備註
- 取得推流 URL：`GET /camera/{id}/publish_rtsp_url` 會簽發短效 JWT，並將 token 以 query string 放入 RTSP URL。\n- MediaMTX 驗證：`deploy/mediamtx/mediamtx.yml` 設定 `authMethod: http`，會回打 `APIServer` 的 `/m2m/check-stream-pwd` 驗證 token。\n- 缺少的關鍵資訊：外部推流端（攝影機/OBS）不在允許 participant 清單中，因此以 note 表示。\n+

