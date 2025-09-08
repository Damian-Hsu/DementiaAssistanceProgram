# run.py
import uvicorn

if __name__ == "__main__":
    # 這裡指定你的 FastAPI app 路徑： services.APIServer.APIService:app
    uvicorn.run(
        "services.APIServer.app.APIService:app",
        host="0.0.0.0",   # 或 "127.0.0.1"
        port=8000,        # 你要的 port
        reload=True       # 開發模式建議 True，上線時要關掉
    )
