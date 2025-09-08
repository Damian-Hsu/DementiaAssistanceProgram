# services/ComputeServer/send_job.py
from services.ComputeServer.CeleryApp import app
import uuid
from services.ComputeServer.DTO import JobCreate

def main():

    job = JobCreate(
        job_id=str(uuid.uuid4()),
        type="audio",  
        segment_uri="http://example.com/audio.wav",
        params={"sleep": 1, "num": 10},
        trace_id="abc123"
    )

    async_result = app.send_task(
        "tasks.echo_and_check",
        kwargs={"job": job.model_dump()},
        queue="default"  # 與 worker 的 -Q default 對齊
    )

    result = async_result.get(timeout=60, propagate=False)
    print("STATE:", async_result.state)
    print("RESULT:", result)

if __name__ == "__main__":
    main()
