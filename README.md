## Development Environment
- OS : windows 11
- python : 3.12.11
## make up
``` 
docker compose -f deploy/docker-compose.yml up
```

## 流程圖
``` mermaid
sequenceDiagram
    autonumber
    actor C as Camera/Windows Publisher
    participant API as API Server
    participant MTX as MediaMTX
    participant STREAM as StreamingServer(FFmpeg分段錄影)
    participant DB as DB/Redis等

    C->>API: POST /camera/{id}/token:generate { action: "publish", ttl, bind_ip }
    API->>DB: 檢查相機狀態/權限
    API->>API: 產生短效 JWT（claims: camera_id, action=publish, exp, ip?）
    API-->>C: { publ_rtsp_url: "rtsp://.../cam-{id}?token=JWT", expires_in }

    C->>MTX: RTSP ANNOUNCE/DESCRIBE/SETUP/PLAY (附 token=JWT 在 URL)
    MTX->>MTX: 驗證 JWT（簽章/exp/token_version/camera_id/action/ip 綁定）
    MTX-->>C: 200 OK（建立會話）

    note over API,STREAM: API 亦可同步簽出「read 用」短效 JWT<br/>交給 StreamingServer 去拉流錄影
    STREAM->>MTX: RTSP PLAY 拉流 (read token)
    MTX-->>STREAM: RTP/RTCP
    STREAM-->>STREAM: ffmpeg 分段錄影(.mp4) → 上傳 MinIO → 建 Job


```
    
Job complete received:
job_id=UUID('01994930-460e-7c70-8f95-232901d63a57') 
trace_id='01994930-460b-71f2-879d-909b6ee438a7' 
status='failed' 
video_start_time='2025-09-14T17:04:45+00:00' 
video_end_time=None error_code='TypeError' 
error_message=
"int() argument must be a string, a bytes-like object or a real number, not 'NoneType'"
duration=0.0012440681457519531 metrics=None events=[]