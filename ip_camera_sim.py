import cv2
import subprocess
import sys
import time

# 推到 mediamtx
rtsp_url = input("請輸入 RTSP 推流 URL:")

cap = cv2.VideoCapture(0)  # 可改成 "sample.mp4"
if not cap.isOpened():
    print("無法開啟影像來源", file=sys.stderr)
    sys.exit(1)

w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
fps = cap.get(cv2.CAP_PROP_FPS)
if not fps or fps <= 1:
    fps = 30  # 有些攝影機/檔案不回 FPS，就手動設

ffmpeg_cmd = [
    "ffmpeg",
    "-loglevel", "warning",
    "-re",                              # 以原速送出（更像即時）
    "-f", "rawvideo",
    "-pix_fmt", "bgr24",
    "-s", f"{w}x{h}",
    "-r", str(int(fps)),
    "-i", "-",                          # 從 stdin 收 raw frame
    "-an",
    "-c:v", "libx264",
    "-preset", "ultrafast",
    "-tune", "zerolatency",
    "-pix_fmt", "yuv420p",              # ★ 重要：避免 4:4:4
    "-rtsp_transport", "tcp",           # 比較穩定
    "-f", "rtsp",
    rtsp_url
]

proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

print(f"RTSP stream started at {rtsp_url}")
try_times = 5
while try_times > 0 or proc.poll() is None:
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            proc.stdin.write(frame.tobytes())
    except BrokenPipeError:
        print("FFmpeg 已中止（可能伺服器未啟動或連線中斷）", file=sys.stderr)
    finally:
        cap.release()
        if proc.stdin:
            proc.stdin.close()
        proc.wait()
    print("重新嘗試連線...")
    for i in range(5, 0, -1):
        print(f"{i}...", end="\r") 
        time.sleep(1)
    try_times -= 1
print("結束推流")
