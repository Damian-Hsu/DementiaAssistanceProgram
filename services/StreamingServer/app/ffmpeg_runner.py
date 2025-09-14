# -*- coding: utf-8 -*-
import os, shlex, subprocess, threading, time, random
from pathlib import Path
from typing import Optional
from .settings import settings
from datetime import datetime, timezone
from .utils import ensure_dir, env_for_utc, seconds_to_next_boundary

class FFmpegProcess:
    """
    同步版子進程：以 subprocess.Popen 管理 ffmpeg。
    - spawn_background(): 在背景執行「啟動重試迴圈」（含 startup 視窗與退避）
    - start(): 單次啟動，不帶重試（給需要立即啟動一次的情境）
    - stop(): 結束子行程並停止背景迴圈
    """

    def __init__(
        self,
        stream_id: str,
        user_id: str,
        camera_id: str,
        input_url: str,
        out_dir: str,
        segment_seconds: int,
        startup_deadline_ts: Optional[int],  # 其實是「啟動重試視窗（秒）」，None 則預設 60 秒
        align_first_cut: bool,
    ):
        self.stream_id = stream_id  # e.g. f"{user_id}-{camera_id}"
        self.user_id = user_id
        self.camera_id = camera_id
        self.input_url = input_url
        self.out_dir = out_dir
        self.segment_seconds = segment_seconds
        self.startup_deadline_ts = startup_deadline_ts
        self.align_first_cut = align_first_cut

        self.cmdline: str = ""
        self.proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = False
        if settings.DEBUG:
            print(f"[DEBUG] FFmpegProcess initialized: stream_id={self.stream_id}, user_id={self.user_id}, camera_id={self.camera_id}, input_url={self.input_url}, out_dir={self.out_dir}, segment_seconds={self.segment_seconds}, startup_deadline_ts={self.startup_deadline_ts}, align_first_cut={self.align_first_cut}")

    # ---------- command 構建 ----------

    def build_cmd(self) -> list[str]:
        # 輸出範本：/root/user_id/camera_id/YYYY/MM/DD/YYYYMMDDTHHMMSSZ.mp4（UTC）
        tpl = os.path.join(self.out_dir, "%Y/%m/%d/%Y%m%dT%H%M%SZ.mp4")
        if settings.DEBUG:
            print(f"[DEBUG] FFmpeg output template: {tpl}")
            print(f"[DEBUG] Ensuring output directory exists: {self.out_dir}")
        ensure_dir(self.out_dir)
        now_utc = datetime.now(timezone.utc)
        date_path = os.path.join(self.out_dir, now_utc.strftime("%Y/%m/%d"))
        ensure_dir(date_path)
    
        args = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "warning",
            "-rtsp_transport", "tcp",
            "-i", self.input_url,
            "-c", "copy",
            "-f", "segment",
            #"-segment_atclocktime", "1",
            "-segment_time", str(self.segment_seconds),
            "-reset_timestamps", "1",
            "-strftime", "1",
            "-segment_format", "mp4",
            "-segment_format_options", "movflags=+faststart",
            # 確保 FFmpeg 使用 UTC 時間
            "-use_wallclock_as_timestamps", "1",
            tpl,
        ]
        # 設定環境變數確保 FFmpeg 使用 UTC
        os.environ['TZ'] = 'UTC'
        if settings.DEBUG:
            args.insert(1, "-loglevel")
            args.insert(2, "debug")
            print(f"[DEBUG] FFmpeg command: {' '.join(shlex.quote(a) for a in args)}")
        return args

    def _open_log(self):
        log_file = os.path.join(settings.log_dir, f"{self.stream_id}.log")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        # 以附加模式開啟，每次啟動各自擁有 file handle；子行程結束後關閉
        if settings.DEBUG:
            print(f"[DEBUG] FFmpeg log file: {log_file}")
        return open(log_file, "ab", buffering=0)

    # ---------- 啟動一次（不重試） ----------

    def _start_once(self, *, align_before_start: bool) -> int:
        """
        回傳子行程退出碼（rc）。
        - align_before_start=True 時，會在第一段前對齊一次。
        """
        if settings.DEBUG:
            print(f"[DEBUG] FFmpegProcess._start_once(align_before_start={align_before_start}) called")

        if align_before_start and self.align_first_cut:
            time.sleep(seconds_to_next_boundary(self.segment_seconds))

        cmd = self.build_cmd()
        self.cmdline = " ".join(shlex.quote(c) for c in cmd)

        logf = self._open_log()
        try:
            self.proc = subprocess.Popen(cmd, env=env_for_utc(), stdout=logf, stderr=logf)

            # 等待結束，但可被 stop() 打斷
            rc = None
            while not self._stop:
                rc = self.proc.poll()
                if rc is not None:
                    if settings.DEBUG:
                        print(f"[DEBUG] FFmpegProcess: process exited with rc={rc}")
                    break
                time.sleep(0.5)

            if self._stop and rc is None:
                # 被要求停止，主動終止
                try:
                    if settings.DEBUG:
                        print(f"[DEBUG] FFmpegProcess: stopping process")
                    self.proc.terminate()
                    rc = self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if settings.DEBUG:
                        print(f"[DEBUG] FFmpegProcess: process did not terminate in time, killing")
                    self.proc.kill()
                    try:
                        rc = self.proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        rc = -9  # 強殺仍卡住，給個特徵碼

            return rc if rc is not None else 0
        finally:
            try:
                logf.close()
                if settings.DEBUG:
                    print(f"[DEBUG] FFmpegProcess: log file closed")
            except Exception:
                pass

    # 對外：單次啟動（不重試）
    def start(self):
        self._stop = False
        _ = self._start_once(align_before_start=True)

    # ---------- 背景重試迴圈 ----------

    def _run_loop(self):
        """
        在「startup 視窗」內以指數退避方式重試啟動；一旦成功跑起，就持續等到：
        - 子行程正常退出（rc==0），或
        - stop() 被呼叫（會終止子行程），或
        - 子行程異常退出，再次進入重試（若仍在視窗內）
        """
        if settings.DEBUG:
            print(f"[DEBUG] FFmpegProcess._run_loop() started")
        self._stop = False
        backoff = 1.0
        first_attempt = True
        deadline = time.time() + (self.startup_deadline_ts or 60)

        while not self._stop and time.time() < deadline:
            try:
                rc = self._start_once(align_before_start=first_attempt)
                first_attempt = False

                if rc == 0:
                    # 子行程「正常結束」—通常代表上游停止或錄製結束；就不再重試
                    break

                if self._stop:
                    break

                # 非 0：視為暫時性錯誤 → 退避重試（含輕微抖動）
                sleep_s = random.uniform(backoff * 0.7, backoff * 1.3)
                time.sleep(sleep_s)
                backoff = min(backoff * 2, 5.0)

            except Exception:
                # 啟動流程本身丟例外，也用退避重試
                sleep_s = random.uniform(backoff * 0.7, backoff * 1.3)
                time.sleep(sleep_s)
                backoff = min(backoff * 2, 5.0)

        # 跳出 while：可能是 stop、超過 deadline、或 rc==0 正常退出
        # 若還有子行程活著，確保結束
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    self.proc.kill()
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass

    def spawn_background(self):
        if settings.DEBUG:
            print(f"[DEBUG] FFmpegProcess.spawn_background() called")
        # 背景跑重試迴圈
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    # ---------- 停止 ----------

    def stop(self):
        if settings.DEBUG:
            print(f"[DEBUG] FFmpegProcess.stop() called")
        self._stop = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        # 等待背景執行緒收尾
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def is_running(self) -> bool:
        if settings.DEBUG:
            print(f"[DEBUG] FFmpegProcess.is_running() called, proc={self.proc}, poll={self.proc.poll() if self.proc else 'N/A'}")
        return bool(self.proc and self.proc.poll() is None)
