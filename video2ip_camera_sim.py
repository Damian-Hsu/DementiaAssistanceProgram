"""
python video2ip_camera_sim.py --video sample.mp4 --rtsp-url        
"""
import argparse
import cv2
import sys
import time
import subprocess
from typing import Optional

def seconds_to_hhmmss(sec: float) -> str:
    sec = max(0, int(sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def draw_hud(frame, text, pos=(10, 28)):
    cv2.putText(frame, text, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (8, 255, 8), 2, cv2.LINE_AA)

def print_progress_bar(curr_sec, total_sec, width=42):
    if total_sec <= 0:
        return
    ratio = min(1.0, curr_sec / total_sec)
    done = int(ratio * width)
    bar = "█" * done + "·" * (width - done)
    print(f"\r[{bar}] {seconds_to_hhmmss(curr_sec)} / {seconds_to_hhmmss(total_sec)}", end="", flush=True)

class RtspPusher:
    def __init__(self, w: int, h: int, fps: float, rtsp_url: str, bitrate: str = "1500k", gop: int = 30):
        self.w, self.h, self.fps = w, h, max(1, int(round(fps or 30)))
        self.rtsp_url = rtsp_url
        self.bitrate = bitrate
        self.gop = gop
        self.proc: Optional[subprocess.Popen] = None

    def start(self):
        cmd = [
            "ffmpeg",
            "-loglevel", "warning",
            "-re",                         # 原速餵入，讓時間基準穩定
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            f"-s", f"{self.w}x{self.h}",
            "-r", str(self.fps),
            "-i", "-",                     # 從 stdin 收 raw frame
            "-an",
            "-c:v", "libx264",
            "-b:v", self.bitrate,
            "-preset", "faster",
            "-tune", "zerolatency",
            "-bf", "0",                     # 禁用 B-frames，WebRTC 相容
            "-g", str(self.gop),
            "-keyint_min", str(self.gop),   # 最小關鍵幀間隔
            "-pix_fmt", "yuv420p",         # 相容性最好
            "-rtsp_transport", "tcp",      # 一般較穩
            "-f", "rtsp",
            self.rtsp_url
        ]
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            print(f"\n[RTSP] 推流啟動：{self.rtsp_url} ({self.w}x{self.h}@{self.fps} • {self.bitrate} • gop={self.gop})")
        except FileNotFoundError:
            print("[ERR] 找不到 ffmpeg（請先安裝或加入 PATH）。", file=sys.stderr)
            sys.exit(1)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None and self.proc.stdin is not None

    def write(self, frame) -> bool:
        if not self.alive():
            return False
        try:
            self.proc.stdin.write(frame.tobytes())
            return True
        except (BrokenPipeError, ValueError):
            return False

    def stop(self):
        if not self.proc:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()
        finally:
            self.proc = None

def open_source(video_path: str = "", camera: Optional[int] = None) -> cv2.VideoCapture:
    if camera is not None:
        cap = cv2.VideoCapture(int(camera))
    else:
        cap = cv2.VideoCapture(video_path)
    return cap

def main():
    ap = argparse.ArgumentParser(description="將影片/攝影機模擬為 IP Cam：視窗顯示 + RTSP 推流（ffmpeg）")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--video", help="影片檔路徑，例如 sample.mp4")
    src.add_argument("--camera", type=int, help="攝影機索引（0=預設相機）")
    ap.add_argument("--rtsp-url", required=True, help="RTSP 目標位址，例如 rtsp://127.0.0.1:30201/mystream")
    ap.add_argument("--max-width", type=int, default=0, help="視窗最大寬度（0=不縮放）")
    ap.add_argument("--bitrate", default="4000k", help="推流碼率，例如 800k / 1500k / 3M")
    ap.add_argument("--gop", type=int, default=0, help="關鍵幀間距（0 代表自動=FPS）")
    ap.add_argument("--repeat-loop", action="store_true", help="影片播完自動循環（僅 --video 時生效）")
    args = ap.parse_args()

    cap = open_source(args.video, args.camera)
    if not cap.isOpened():
        print("無法開啟來源", file=sys.stderr); sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if fps < 1: fps = 30.0
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)  or 640)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    total_duration = (total_frames / fps) if total_frames > 0 else 0.0

    gop = args.gop if args.gop > 0 else int(round(fps))

    pusher = RtspPusher(width, height, fps, args.rtsp_url, bitrate=args.bitrate, gop=gop)
    pusher.start()

    window = "IPCam 模擬串流"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    print(f"[INFO] 來源: {'camera:'+str(args.camera) if args.camera is not None else args.video}")
    if total_duration > 0:
        print(f"[INFO] 長度：{seconds_to_hhmmss(total_duration)}，FPS={fps:.2f}，解析度={width}x{height}")
    else:
        print(f"[INFO] FPS={fps:.2f}，解析度={width}x{height}（即時來源或無法取得總長）")
    print("按 q 離開。")
    print_progress_bar(0, total_duration)

    frame_interval = 1.0 / fps
    next_show_time = time.perf_counter()

    while True:
        ret, frame = cap.read()
        if not ret:
            if args.video and args.repeat_loop:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            break

        # 目前秒數（用 frame index 估算；對相機來源則無總長、僅顯示流逝時間）
        frame_idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        curr_sec = (frame_idx / fps) if total_duration > 0 else (frame_idx / fps)

        # 疊字 HUD
        if total_duration > 0:
            hud = f"{seconds_to_hhmmss(curr_sec)} / {seconds_to_hhmmss(total_duration)}"
        else:
            hud = f"{seconds_to_hhmmss(curr_sec)}"
        draw_hud(frame, hud, (10, 28))

        # 視窗縮放顯示
        show = frame
        if args.max_width and width > args.max_width:
            scale = args.max_width / width
            show = cv2.resize(frame, (int(width*scale), int(height*scale)), interpolation=cv2.INTER_AREA)

        # 節奏控制，盡量貼合原 fps
        now = time.perf_counter()
        if now < next_show_time:
            time.sleep(max(0, next_show_time - now))
        cv2.imshow(window, show)
        next_show_time = time.perf_counter() + frame_interval

        # 推流；若 ffmpeg 掛了就嘗試重啟
        ok = pusher.write(frame)
        if not ok:
            print("\n[RTSP] 偵測到 ffmpeg 中斷，3 秒後嘗試重連...")
            pusher.stop()
            time.sleep(3)
            pusher.start()

        if total_duration > 0:
            print_progress_bar(curr_sec, total_duration)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    pusher.stop()
    print("\n串流結束。")

if __name__ == "__main__":
    main()
