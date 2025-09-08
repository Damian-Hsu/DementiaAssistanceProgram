from libs.LogConfig import setup_logging, get_logger, set_trace_id
import uuid, os

setup_logging(service_name="tester", file_path="datas/logs/logs.log")
log = get_logger(__name__)

def test_trace_id():
    trace = str(uuid.uuid4())
    set_trace_id(trace)
    log.info("This is a test log with trace_id", extra={"trace_id": trace})
    set_trace_id(None)  # 清理 trace_id
if __name__ == "__main__":
    test_trace_id()
    log.info("Test completed successfully.")
