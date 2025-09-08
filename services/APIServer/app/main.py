# -*- coding: utf-8 -*-
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from .security.deps import get_current_user, get_current_api_client
from .config.path import (API_ROOT)
from .router.Authentication.service import auth_router, m2m_router
from .router.User.service import user_router
from .router.Admin.service import admin_router
from .router.Jobs.service import jobs_router
from .router.Camera.service import camera_router
"""
這個檔案負責"呼叫"各個Business Logic Functions，並提供API介面。
規劃：
    此API需要面對使用者前端、計算伺服器、硬體設備等，所以需要一個完善的統一架構。
    1. 使用 FastAPI 作為 Web 框架。
    2. 使用 SQLAlchemy 作為 ORM，連接到資料庫。
    3. 使用 Pydantic 定義資料模型，確保資料的完整性和驗證。
    4. 使用 JWT 進行使用者認證和授權。
    5. 提供 RESTful API 接口，讓前端和其他服務可以輕鬆調用。
    6. 使用依賴注入（Dependency Injection）來管理資料庫連接和使用者認證。
    7. 提供錯誤處理和日誌記錄功能，方便調試和維護。
    8. 提供 Swagger UI 介面，方便前端開發人員和測試人員查看和測試 API。
    9. 提供 CORS 支持，允許跨域請求。
    10. 提供環境變數配置，方便部署和配置。
    11. 提供健康檢查 API，方便監控和維護。
    12. 提供版本控制，方便未來擴展和維護。
    13. 提供統一的錯誤處理機制

API 功能規劃：
    - 權限守門員（Authentication）
    - 使用者註冊（Signup）
    - 使用者登入（Login）
    - 使用者登出（Logout）
    
"""

app = FastAPI(root_path=API_ROOT, title="Dementia Assistance Program API", version="1.0.0")


# ALLOWED_ORIGINS = [
#     "http://localhost:8080",
#     "http://127.0.0.1:8080",
#     # "http://localhost:9090",
# ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=600,  # 預檢快取
)


# 基本權限控制路由，公開
app.include_router(auth_router)
# 機器對機器的測試路由，要使用 API Key(header: X-API-Key)
app.include_router(m2m_router, dependencies=[Depends(get_current_api_client)])
app.include_router(jobs_router,dependencies=[Depends(get_current_api_client)])
app.include_router(user_router, dependencies=[Depends(get_current_user)])
app.include_router(admin_router, dependencies=[Depends(get_current_user)])
app.include_router(camera_router, dependencies=[Depends(get_current_user)])
# ======================== User Signup API =======================

@app.get("/")
async def read_root():
    """
    測試 API 是否連線
    """
    return {"message": "Connected to FastAPI Server! You need to use /api/v1 to access the API."}

@app.get("/healthz", tags=["health"])
async def health_check():
    """
    健康檢查 API
    """
    return {"status": "ok"}