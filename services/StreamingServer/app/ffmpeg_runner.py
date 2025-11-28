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
        startup_deadline_ts: Optional[int],  # 「啟動重試視窗（秒）」，None 則預設 60 秒
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
        self.last_error: Optional[str] = None
        self.process_started_time: Optional[float] = None  # 記錄進程成功啟動的時間
        self.disconnect_start_time: Optional[float] = None  # 記錄斷線開始時間
        self._log_file_handle: Optional[object] = None  # 保持 log 文件打開
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
            "-rtsp_flags", "prefer_tcp",  # 優先使用 TCP
            "-timeout", "5000000",  # 5 秒超時（微秒）
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
            "-avoid_negative_ts", "make_zero",  # 避免負時間戳
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

    def _start_once(self, *, align_before_start: bool, wait_for_exit: bool = True) -> int:
        """
        啟動進程並可選地等待退出。
        - align_before_start=True 時，會在第一段前對齊一次。
        - wait_for_exit=False 時，啟動後立即返回 -999（表示進程正在運行）
        - wait_for_exit=True 時，等待進程結束並返回退出碼
        """
        if settings.DEBUG:
            print(f"[DEBUG] FFmpegProcess._start_once(align_before_start={align_before_start}, wait_for_exit={wait_for_exit}) called")

        if align_before_start and self.align_first_cut:
            time.sleep(seconds_to_next_boundary(self.segment_seconds))

        cmd = self.build_cmd()
        self.cmdline = " ".join(shlex.quote(c) for c in cmd)

        logf = self._open_log()
        try:
            self.proc = subprocess.Popen(cmd, env=env_for_utc(), stdout=logf, stderr=logf)
            
            if settings.DEBUG:
                print(f"[DEBUG] FFmpegProcess: process started with PID={self.proc.pid}")

            # 如果不需要等待退出，保持 logf 打開並立即返回
            if not wait_for_exit:
                self._log_file_handle = logf  # 保存引用，避免被垃圾回收
                return -999  # 特殊值表示進程正在運行

            # 等待結束，但可被 stop() 打斷
            rc = None
            while not self._stop:
                rc = self.proc.poll()
                if rc is not None:
                    # 讀取日誌文件的最後幾行來診斷問題
                    error_msg = None
                    try:
                        log_file = os.path.join(settings.log_dir, f"{self.stream_id}.log")
                        if os.path.exists(log_file):
                            with open(log_file, "rb") as f:
                                # 讀取最後 2KB
                                f.seek(max(0, os.path.getsize(log_file) - 2048))
                                last_lines = f.read().decode("utf-8", errors="ignore").split("\n")[-10:]
                                if settings.DEBUG:
                                    print(f"[DEBUG] FFmpegProcess: process exited with rc={rc}")
                                    print(f"[DEBUG] FFmpegProcess: Last log lines:")
                                    for line in last_lines:
                                        if line.strip():
                                            print(f"[DEBUG]   {line}")
                                # 提取錯誤訊息
                                for line in reversed(last_lines):
                                    if "Connection refused" in line or "Connection to" in line:
                                        error_msg = line.strip()
                                        break
                                    if "Error opening input" in line:
                                        error_msg = line.strip()
                                        break
                    except Exception as log_err:
                        if settings.DEBUG:
                            print(f"[DEBUG] Failed to read log file: {log_err}")
                    
                    # 如果是連接錯誤，記錄更詳細的資訊
                    if error_msg and ("Connection refused" in error_msg or "Error opening input" in error_msg):
                        self.last_error = error_msg
                        print(f"[ERROR] FFmpegProcess: Failed to connect to MediaMTX for stream {self.stream_id}")
                        print(f"[ERROR]   Input URL: {self.input_url}")
                        print(f"[ERROR]   Error: {error_msg}")
                        print(f"[ERROR]   Possible causes:")
                        print(f"[ERROR]     1. MediaMTX service is not running")
                        print(f"[ERROR]     2. MediaMTX is not accessible at {settings.mediamtx_rtsp_base}")
                        print(f"[ERROR]     3. Stream path does not exist (publisher not started yet)")
                        print(f"[ERROR]     4. Network connectivity issue between StreamingServer and MediaMTX")
                    elif settings.DEBUG:
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
            # 注意：如果 wait_for_exit=False，logf 不能關閉，因為進程還在運行
            if wait_for_exit:
                try:
                    logf.close()
                    if settings.DEBUG:
                        print(f"[DEBUG] FFmpegProcess: log file closed")
                except Exception:
                    pass

    # 對外：單次啟動（不重試）
    def start(self):
        self._stop = False
        _ = self._start_once(align_before_start=True, wait_for_exit=True)

    # ---------- 背景重試迴圈 ----------

    def _run_loop(self):
        """
        持續監控和重試機制：
        1. 啟動階段：在 startup_deadline_ts 內以指數退避方式重試啟動
        2. 運行階段：一旦成功啟動，持續監控進程；如果因網路問題退出（rc != 0），
           給1分鐘的重連容許時間，在此期間持續重試
        3. 正常退出（rc==0）或 stop() 被呼叫時，停止重試
        """
        if settings.DEBUG:
            print(f"[DEBUG] FFmpegProcess._run_loop() started")
        self._stop = False
        backoff = 1.0
        first_attempt = True
        startup_deadline = time.time() + (self.startup_deadline_ts or 60)
        RECONNECT_GRACE_PERIOD = 60  # 1分鐘重連容許時間

        while not self._stop:
            try:
                # 如果進程已經成功啟動過，檢查是否還在運行
                if self.process_started_time is not None and self.proc:
                    poll_result = self.proc.poll()
                    if poll_result is None:
                        # 進程還在運行，等待一段時間後再檢查
                        time.sleep(2)
                        backoff = 1.0  # 重置退避時間
                        self.disconnect_start_time = None  # 清除斷線計時
                        continue
                    elif poll_result == 0:
                        # 正常退出，停止重試
                        if settings.DEBUG:
                            print(f"[DEBUG] FFmpegProcess._run_loop: process exited normally (rc=0), stopping retry loop")
                        break
                    else:
                        # 異常退出（rc != 0），可能是網路問題
                        # 讀取錯誤訊息
                        error_msg = None
                        try:
                            log_file = os.path.join(settings.log_dir, f"{self.stream_id}.log")
                            if os.path.exists(log_file):
                                with open(log_file, "rb") as f:
                                    f.seek(max(0, os.path.getsize(log_file) - 2048))
                                    last_lines = f.read().decode("utf-8", errors="ignore").split("\n")[-10:]
                                    for line in reversed(last_lines):
                                        if "Connection refused" in line or "Connection to" in line:
                                            error_msg = line.strip()
                                            break
                                        if "Error opening input" in line:
                                            error_msg = line.strip()
                                            break
                        except Exception:
                            pass
                        
                        if error_msg:
                            self.last_error = error_msg
                        
                        if self.disconnect_start_time is None:
                            self.disconnect_start_time = time.time()
                            if settings.DEBUG:
                                print(f"[DEBUG] FFmpegProcess._run_loop: process exited with rc={poll_result}, starting reconnect grace period")
                        
                        # 檢查是否超過重連容許時間
                        disconnect_duration = time.time() - self.disconnect_start_time
                        if disconnect_duration >= RECONNECT_GRACE_PERIOD:
                            if settings.DEBUG:
                                print(f"[DEBUG] FFmpegProcess._run_loop: reconnect grace period ({RECONNECT_GRACE_PERIOD}s) exceeded, stopping retry loop")
                            break
                        
                        # 還在容許時間內，重試連接（繼續到下面的啟動邏輯）
                        if settings.DEBUG:
                            remaining = RECONNECT_GRACE_PERIOD - disconnect_duration
                            print(f"[DEBUG] FFmpegProcess._run_loop: process exited with rc={poll_result}, retrying (remaining grace time: {remaining:.1f}s)")
                
                # 啟動或重啟進程（不等待退出，立即返回）
                rc = self._start_once(align_before_start=first_attempt, wait_for_exit=False)
                first_attempt = False

                if self._stop:
                    if settings.DEBUG:
                        print(f"[DEBUG] FFmpegProcess._run_loop: stop requested, exiting loop")
                    break

                # 檢查進程是否成功啟動
                if self.proc and self.proc.poll() is None:
                    # 進程正在運行，標記為已啟動
                    self.process_started_time = time.time()
                    self.disconnect_start_time = None  # 清除斷線計時
                    backoff = 1.0  # 重置退避時間
                    if settings.DEBUG:
                        print(f"[DEBUG] FFmpegProcess._run_loop: process started successfully, monitoring...")
                    # 繼續監控，不要立即重試
                    time.sleep(2)
                    continue
                else:
                    # 進程啟動失敗，等待一小段時間後重試
                    # 但只在啟動階段（startup_deadline_ts 內）重試
                    if time.time() >= startup_deadline:
                        if settings.DEBUG:
                            print(f"[DEBUG] FFmpegProcess._run_loop: startup deadline reached, stopping retry loop")
                        break
                    
                    if settings.DEBUG:
                        print(f"[DEBUG] FFmpegProcess._run_loop: process failed to start immediately, will retry after {backoff:.1f}s")
                    sleep_s = random.uniform(backoff * 0.7, backoff * 1.3)
                    time.sleep(sleep_s)
                    backoff = min(backoff * 2, 5.0)
                    continue

            except Exception as e:
                # 啟動流程本身丟例外，也用退避重試
                if time.time() >= startup_deadline:
                    if settings.DEBUG:
                        print(f"[DEBUG] FFmpegProcess._run_loop: startup deadline reached after exception, stopping retry loop")
                    break
                
                if settings.DEBUG:
                    print(f"[DEBUG] FFmpegProcess._run_loop: exception during start: {e}, will retry after {backoff:.1f}s")
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
        
        # 清除狀態
        self.process_started_time = None
        self.disconnect_start_time = None
        # 關閉 log 文件（如果還在打開）
        if self._log_file_handle:
            try:
                self._log_file_handle.close()
            except Exception:
                pass
            self._log_file_handle = None

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
        if not self.proc:
            return False
        poll_result = self.proc.poll()
        is_alive = poll_result is None
        if settings.DEBUG:
            print(f"[DEBUG] FFmpegProcess.is_running() called, proc={self.proc}, pid={self.proc.pid if self.proc else None}, poll={poll_result}, is_alive={is_alive}")
        return is_alive
