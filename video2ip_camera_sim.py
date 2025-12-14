"""
python video2ip_camera_sim.py --video video_samples/5.mp4 --rtsp-url 
"""

import argparse
import cv2
import sys
import time
import subprocess
import queue
import threading

from typing import Optional

OUTPUT_FPS = 30.0   # <<< 固定輸出 FPS

def seconds_to_hhmmss(sec: float) -> str:
    sec = max(0, int(sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def print_progress_bar(curr_sec, total_sec, width=42):
    if total_sec <= 0:
        return
    ratio = min(1.0, curr_sec / total_sec)
    done = int(ratio * width)
    bar = "█" * done + "·" * (width - done)
    print(f"\r[{bar}] {seconds_to_hhmmss(curr_sec)} / {seconds_to_hhmmss(total_sec)}", end="", flush=True)

class RtspPusher:
    def __init__(self, w: int, h: int, fps: float, rtsp_url: str, bitrate: str = "1500k", gop: int = 30):
        self.w, self.h, self.fps = w, h, int(round(fps))
        self.rtsp_url = rtsp_url
        self.bitrate = bitrate
        self.gop = gop
        self.proc: Optional[subprocess.Popen] = None

        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=self.fps * 2)
        self._writer_thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()

    def start(self):
        cmd = [
            "ffmpeg",
            "-loglevel", "warning",
            "-re",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{self.w}x{self.h}",
            "-r", str(self.fps),
            "-i", "-",
            "-an",
            "-c:v", "libx264",
            "-b:v", self.bitrate,
            "-preset", "faster",
            "-tune", "zerolatency",
            "-bf", "0",
            "-g", str(self.gop),
            "-keyint_min", str(self.gop),
            "-pix_fmt", "yuv420p",
            "-rtsp_transport", "tcp",
            "-f", "rtsp",
            self.rtsp_url
        ]
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            self._stop_flag.clear()
            self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
            self._writer_thread.start()
            print(f"\n[RTSP] 推流啟動：{self.rtsp_url} ({self.w}x{self.h}@{self.fps}fps)")
        except FileNotFoundError:
            print("[ERR] 找不到 ffmpeg", file=sys.stderr)
            sys.exit(1)

    def _writer_loop(self):
        if self.proc is None or self.proc.stdin is None:
            return
        try:
            while not self._stop_flag.is_set():
                try:
                    frame_bytes = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    self.proc.stdin.write(frame_bytes)
                except (BrokenPipeError, ValueError):
                    break
        finally:
            try:
                if self.proc and self.proc.stdin:
                    self.proc.stdin.close()
            except Exception:
                pass

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def write(self, frame) -> bool:
        if not self.alive():
            return False
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
        try:
            self._queue.put_nowait(frame.tobytes())
            return True
        except queue.Full:
            return True

    def stop(self):
        if not self.proc:
            return
        self._stop_flag.set()
        try:
            if self._writer_thread and self._writer_thread.is_alive():
                self._writer_thread.join(timeout=1.0)
        except Exception:
            pass
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()
        finally:
            self.proc = None
            self._writer_thread = None
            with self._queue.mutex:
                self._queue.queue.clear()

def open_source(video_path: str = "", camera: Optional[int] = None) -> cv2.VideoCapture:
    return cv2.VideoCapture(int(camera)) if camera is not None else cv2.VideoCapture(video_path)

def main():
    ap = argparse.ArgumentParser(description="將影片/攝影機模擬為 IP Cam（固定 30 FPS RTSP）")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--video")
    src.add_argument("--camera", type=int)
    ap.add_argument("--rtsp-url", required=True)
    ap.add_argument("--max-width", type=int, default=0)
    ap.add_argument("--bitrate", default="4000k")
    ap.add_argument("--gop", type=int, default=0)
    ap.add_argument("--repeat-loop", action="store_true")
    args = ap.parse_args()

    cap = open_source(args.video, args.camera)
    if not cap.isOpened():
        print("無法開啟來源", file=sys.stderr)
        sys.exit(1)

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if src_fps < 1:
        src_fps = 30.0

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    total_duration = total_frames / src_fps if total_frames > 0 else 0.0

    drop_ratio = max(1, round(src_fps / OUTPUT_FPS))
    frame_interval = 1.0 / OUTPUT_FPS

    gop = args.gop if args.gop > 0 else int(OUTPUT_FPS)
    pusher = RtspPusher(width, height, OUTPUT_FPS, args.rtsp_url, bitrate=args.bitrate, gop=gop)
    pusher.start()

    cv2.namedWindow("IPCam 模擬串流", cv2.WINDOW_NORMAL)
    print(f"[INFO] Source FPS={src_fps:.2f} → Output FPS={OUTPUT_FPS}")
    print("按 q 離開")

    next_time = time.perf_counter()
    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            if args.video and args.repeat_loop:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                frame_count = 0
                continue
            break

        frame_count += 1
        if frame_count % drop_ratio != 0:
            continue

        now = time.perf_counter()
        if now < next_time:
            time.sleep(next_time - now)

        show = frame
        if args.max_width and width > args.max_width:
            scale = args.max_width / width
            show = cv2.resize(frame, (int(width * scale), int(height * scale)))

        cv2.imshow("IPCam 模擬串流", show)
        next_time = time.perf_counter() + frame_interval

        if not pusher.write(frame):
            print("\n[RTSP] ffmpeg 中斷，3 秒後重連")
            pusher.stop()
            time.sleep(3)
            pusher.start()

        if total_duration > 0:
            curr_sec = (frame_count * drop_ratio) / src_fps
            print_progress_bar(curr_sec, total_duration)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    pusher.stop()
    print("\n串流結束")

if __name__ == "__main__":
    main()
