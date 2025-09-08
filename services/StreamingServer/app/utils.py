# -*- coding: utf-8 -*-
import time, asyncio, os
from pathlib import Path

def ensure_dir(p: str):
    Path(p).mkdir(parents=True, exist_ok=True)

def seconds_to_next_boundary(seconds: int) -> float:
    now = time.time()
    nb = ((int(now)//seconds)+1)*seconds
    return max(0.0, nb - now)

async def asleep_until_next_boundary(seconds: int):
    to_sleep = seconds_to_next_boundary(seconds)
    if to_sleep > 0:
        await asyncio.sleep(to_sleep)

def env_for_utc():
    env = os.environ.copy()
    env["TZ"] = "UTC"
    return env
