# -*- coding: utf-8 -*-
import asyncio, os
from typing import Dict, Tuple, List
from pathlib import Path
import uuid, hashlib, base64
from .settings import settings
from .ffmpeg_runner import FFmpegProcess
from .models import StreamInfo
from .utils import asleep_until_next_boundary

class _Manager:
    def __init__(self):
        # key=(user_id,camera_id,path) -> FFmpegProcess
        self.active: Dict[Tuple[str,str], FFmpegProcess] = {}

    def _record_dir(self, user_id:str, camera_id:str ) -> str:
        return str(Path(settings.record_root) / user_id / camera_id)
    
    def _stream_id(self, user_id: str, camera_id: str) -> Tuple[str,str]:
        return (user_id, camera_id) 
    
    def to_info(self, p: FFmpegProcess) -> StreamInfo:
        status = "running" if p.is_running() else "stopped"
        return StreamInfo(
            stream_id=p.stream_id,
            user_id=p.user_id,
            camera_id=p.camera_id,
            input_url=p.input_url, # 動態塞給 instance（見 start）
            record_dir=p.out_dir, # 同上
            segment_seconds=p.segment_seconds,
            align_first_cut=p.align_first_cut,
            pid=(p.proc.pid if p.proc else None),
            status=status,
            cmdline=p.cmdline
        )

    def list(self) -> List[StreamInfo]:
        out: List[StreamInfo] = []
        for _, p in self.active.items():
            out.append(self.to_info(p))
        return out

    def start(self,
              user_id: str,
              camera_id: str,
              rtsp_url: str,
              segment_seconds: int | None,
              align_first_cut: bool | None,
              startup_deadline_ts: int | None) -> FFmpegProcess:
        
        key = self._stream_id(user_id, camera_id)
        exist = self.active.get(key)
        if exist and exist.is_running():
            return exist

        seg = segment_seconds or settings.segment_seconds
        align = settings.align_first_cut if align_first_cut is None else align_first_cut
        out_dir = self._record_dir(user_id, camera_id)

        p = FFmpegProcess(
            stream_id=f"{user_id}-{camera_id}",
            user_id=user_id,
            camera_id=camera_id,
            input_url=rtsp_url,
            out_dir=out_dir,
            segment_seconds=seg,
            align_first_cut=align,
            startup_deadline_ts = startup_deadline_ts
        )

        # 啟動（同步），避免阻塞 API 的話可用 asyncio.to_thread（但 start 在路由中是同步呼叫）
        p.spawn_background()
        self.active[key] = p
        return p

    def stop(self, user_id: str, camera_id: str):
        key = self._stream_id(user_id, camera_id)
        p = self.active.get(key)
        if p:
            p.stop()
            self.active.pop(key, None)

    async def update(self,
                     user_id: str,
                     camera_id: str,
                     rtsp_url: str,
                     segment_seconds: int | None,
                     align_first_cut: bool | None,
                     graceful: bool = True):
        key = self._stream_id(user_id, camera_id)
        old = self.active.get(key)
        if not old:
            return self.to_info(
                self.start(
                user_id,
                camera_id,
                rtsp_url=rtsp_url,
                segment_seconds=segment_seconds,
                align_first_cut=align_first_cut
            ))

        new_seg = segment_seconds if segment_seconds is not None else old.segment_seconds
        new_align = old.align_first_cut if align_first_cut is None else align_first_cut

        async def _restart_async():
            if graceful:
                await asleep_until_next_boundary(new_seg)
            # 停舊、起新都丟到 thread pool（因為是同步 Popen/terminate）
            await asyncio.to_thread(old.stop)

            np = FFmpegProcess(
                stream_id=old.stream_id,
                user_id=old.user_id,
                camera_id=old.camera_id,
                input_url=rtsp_url, # 新的 URL
                out_dir=old.out_dir,
                segment_seconds=new_seg, # 新的切片秒數
                align_first_cut=new_align, # 新的對齊設定
                startup_deadline_ts = old.startup_deadline_ts
            )
            await asyncio.to_thread(np.start())
            self.active[key] = np

        asyncio.create_task(_restart_async())
        return {"scheduled": True,
                "graceful": graceful,
                "new_segment_seconds": new_seg,
                "new_align_first_cut": new_align}

manager = _Manager()
