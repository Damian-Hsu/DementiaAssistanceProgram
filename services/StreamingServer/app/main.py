# -*- coding: utf-8 -*-
from fastapi import FastAPI, Header, HTTPException, Depends
from typing import Optional, List
from urllib.parse import urlencode
import jwt, time
from contextlib import asynccontextmanager
from .models import StartStreamReq, UpdateStreamReq, StopStreamReq, StreamInfo
from .settings import settings
from .manager import manager
from .uploader_worker import bootstrap_uploader
from .ffmpeg_runner import FFmpegProcess
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not getattr(app.state, "uploader_started", False):
        app.state.uploader_started = True
        bootstrap_uploader()
    try:
        yield
    finally:
        # 這裡可以做關閉清理，例如發一個 stop event 給 worker
        # stop_uploader_event.set()
        pass
# @app.on_event("startup")
# def _start_background_workers():
#     # 啟動 Uploader（watchdog + worker），以及預先掃描既有檔案
#     bootstrap_uploader()

app = FastAPI(title="StreamingServer", version="0.3.0", lifespan=lifespan)

def _auth(x_internal_token: Optional[str] = Header(default=None, alias="X-Internal-Token")):
    if not settings.internal_token or x_internal_token != settings.internal_token:
        raise HTTPException(status_code=401, detail="unauthorized")

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/streams", response_model=List[StreamInfo])
def list_streams(_: None = Depends(_auth)):
    return manager.list()

@app.post("/streams/start", response_model=StreamInfo)
def start_stream(req: StartStreamReq, _: None = Depends(_auth)):
    p : FFmpegProcess = manager.start(
                        user_id=req.user_id,
                        camera_id=req.camera_id,
                        rtsp_url=str(req.rtsp_url) if req.rtsp_url else None,
                        segment_seconds=req.segment_seconds,
                        align_first_cut=req.align_first_cut,
                        startup_deadline_ts=req.startup_deadline_ts
                        )
    info = manager.to_info(p)
    # 立刻標示為 starting（或 running，如果你能瞬間判定）
    info.status = "running" if p.is_running() else "starting"
    # 可選：把這次使用的拉流 URL 帶回做觀察性
    info.input_url = str(req.rtsp_url)
    return info
@app.post("/streams/stop")
def stop_stream(req: StopStreamReq, _: None = Depends(_auth)):
    manager.stop(req.user_id, req.camera_id)
    return {"ok": True}

@app.patch("/streams/update")
async def update_stream(req: UpdateStreamReq, _: None = Depends(_auth)):
    out = await manager.update(
        user_id=req.user_id,
        camera_id=req.camera_id,
        rtsp_url= req.rtsp_url,
        segment_seconds=req.segment_seconds,
        align_first_cut=req.align_first_cut,
        startup_deadline_ts=req.startup_deadline_ts,
        graceful=req.graceful,
    )
    return out
