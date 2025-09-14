# services/ComputeServer/tasks/test.py
from time import sleep
from celery.exceptions import SoftTimeLimitExceeded
from ..main import app
from ..DTO import JobCreate

@app.task(name="tasks.echo_and_check", bind=True, acks_late=True)
def echo_and_check(self, job: dict):
    try:
        spec = JobCreate(**job)  # ← 在任務內做驗證/轉型
    except Exception as e:
        return {"ok": False, "status": "error", "job_id": job.get("job_id","?"),
                "name": None, "num": -1,
                "error": {"type": "ValidationError", "message": str(e)}}

    job_id = spec.job_id
    # name 不在 JobSpec，建議放到 params 裡
    name   = (spec.params or {}).get("name", "未命名任務")
    params = spec.params or {}

    try:
        sleep(int(params.get("sleep", 2)))
        ok  = bool(params.get("ok", True))
        num = int(params.get("num", 0)) ** 2

        if not ok:
            return {
                "ok": False, "status": "failed",
                "job_id": job_id, "name": name, "num": -1,
                "error": {"type": "BusinessRule", "message": "條件不成立"},
            }

        return {
            "ok": True, "status": "finished",
            "job_id": job_id, "name": name, "num": num,
            "message": f"{name}（job_id={job_id}）→ 任務完成",
        }

    except SoftTimeLimitExceeded:
        return {
            "ok": False, "status": "timeout",
            "job_id": job_id, "name": name, "num": -1,
            "error": {"type": "SoftTimeLimitExceeded", "message": "任務超時"},
        }
    except Exception as e:
        return {
            "ok": False, "status": "error",
            "job_id": job_id, "name": name, "num": -1,
            "error": {"type": e.__class__.__name__, "message": str(e)},
        }