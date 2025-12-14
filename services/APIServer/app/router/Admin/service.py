# -*- coding: utf-8 -*-
from __future__ import annotations
from uuid import UUID
import os
import httpx
from typing import Optional

from fastapi import APIRouter, Request, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from ...DataAccess.Connect import get_session
from ...DataAccess.tables import api_keys, users, settings as settings_table, api_key_blacklist
from ...security.deps import get_current_user
from ...security.api_key_manager import APIKeyManager, APIKeyManagerConfig
from .DTO import (
    ApiKeyCreateDTO,
    ApiKeyOutDTO,
    ApiKeyPatchDTO,
    ApiKeySecretOutDTO,
    SetDefaultGoogleApiKeyDTO,
    DefaultGoogleApiKeyResponse,
    SetDefaultLLMDTO,
    DefaultLLMResponse,
    SetVideoParamsDTO,
    VideoParamsResponse,
    SetDefaultAiKeyLimitsDTO,
    DefaultAiKeyLimitsResponse,
    AddToBlacklistDTO,
    BlacklistEntryDTO,
    UserStatsDTO,
    UserDetailDTO,
    UpdateUserActiveDTO,
    TaskInfoDTO,
    TaskListRespDTO,
)
from ...config.path import (
    ADMIN_PREFIX,
    ADMIN_POST_CREATE_KEY,
    ADMIN_GET_LIST_KEYS,
    ADMIM_PATCH_UPDATE_KEY,
    ADMIN_POST_ROTATE_KEY,
)

admin_router = APIRouter(prefix=ADMIN_PREFIX, tags=["admin"])


api_key_mgr = APIKeyManager(APIKeyManagerConfig(header_name="X-API-Key"))

def ensure_admin(u: users.Table):
    if u.role != users.Role.admin:
        raise HTTPException(status_code=403, detail="Admin only")


@admin_router.post(
    ADMIN_POST_CREATE_KEY,
    response_model=ApiKeySecretOutDTO,
    status_code=status.HTTP_201_CREATED,
)
async def create_key(
    request: Request,
    body: ApiKeyCreateDTO,
    db: AsyncSession = Depends(get_session),
):
    current_user = request.state.current_user
    ensure_admin(current_user)

    # owner 存在檢查
    res = await db.execute(select(users.Table).where(users.Table.id == body.owner_id))
    if not res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Owner user not found")

    # 透過 manager 建立（回傳 DB 記錄 + 明碼 token〈只此一次〉）
    rec, token = await api_key_mgr.create(
        db,
        name=body.name,
        owner_id=body.owner_id,
        scopes=body.scopes,
        rate_limit_per_min=body.rate_limit_per_min,
        quota_per_day=body.quota_per_day,
        active=True,
    )

    return ApiKeySecretOutDTO.model_validate(
        {**ApiKeyOutDTO.model_validate(rec).model_dump(), "token": token}
    )


@admin_router.get(ADMIN_GET_LIST_KEYS, response_model=list[ApiKeyOutDTO])
async def list_keys(
    request: Request,
    db: AsyncSession = Depends(get_session),
    owner_id: int | None = Query(None, description="依擁有者過濾（可選）"),
):
    """列出所有 M2M API Keys。
    
    Args:
        request: FastAPI Request 對象
        db: 資料庫會話
        owner_id: 可選的擁有者 ID 過濾條件
        
    Returns:
        list[ApiKeyOutDTO]: API Key 列表
    """
    current_user = request.state.current_user
    ensure_admin(current_user)

    # 查詢 API Key 列表（可選 owner_id 過濾）
    records = await api_key_mgr.list_all(db, owner_id=owner_id)
    return [ApiKeyOutDTO.model_validate(r) for r in records]


@admin_router.patch(ADMIM_PATCH_UPDATE_KEY, response_model=ApiKeyOutDTO)
async def update_key(
    request: Request,
    key_id: UUID,
    body: ApiKeyPatchDTO,
    db: AsyncSession = Depends(get_session)
):
    """更新 M2M API Key。
    
    Args:
        request: FastAPI Request 對象
        key_id: API Key ID（UUIDv7）
        body: 更新資料
        db: 資料庫會話
        
    Returns:
        ApiKeyOutDTO: 更新後的 API Key 資訊
    """
    current_user = request.state.current_user
    ensure_admin(current_user)

    # 取得目標 API Key
    rec = await api_key_mgr.get(db, key_id=key_id)

    patch = body.model_dump(exclude_unset=True)
    
    # 如果只更新 active 狀態，使用專門的方法
    if "active" in patch and len(patch) == 1:
        rec = await api_key_mgr.set_active(db, key_id=key_id, active=bool(patch["active"]))
    else:
        # 如果更新 scopes，使用專門的方法來確保驗證和正規化
        if "scopes" in patch:
            scopes = patch.pop("scopes")
            rec = await api_key_mgr.set_scopes(db, key_id=key_id, scopes=scopes or [])
        
        # 更新其他欄位
        if patch:
            for k, v in patch.items():
                setattr(rec, k, v)
            db.add(rec)
            await db.commit()
            await db.refresh(rec)

    return ApiKeyOutDTO.model_validate(rec)


@admin_router.post(
    ADMIN_POST_ROTATE_KEY,
    response_model=ApiKeySecretOutDTO,
    status_code=status.HTTP_201_CREATED,
)
async def rotate_key(
    request: Request,
    key_id: UUID,
    db: AsyncSession = Depends(get_session),
    current_user: users.Table = Depends(get_current_user),
):
    current_user = request.state.current_user
    ensure_admin(current_user)

    # 用 manager 旋轉（回新 token，舊 token 立即失效）
    rec, token = await api_key_mgr.rotate(db, key_id=key_id)

    return ApiKeySecretOutDTO.model_validate(
        {**ApiKeyOutDTO.model_validate(rec).model_dump(), "token": token}
    )


# ====== 系統設定 API ======

@admin_router.post("/settings/default-google-api-key", response_model=DefaultGoogleApiKeyResponse)
async def set_default_google_api_key(
    request: Request,
    body: SetDefaultGoogleApiKeyDTO,
    db: AsyncSession = Depends(get_session),
):
    """設置系統預設的 Google API Key。
    
    Args:
        request: FastAPI Request 對象
        body: 包含 API Key 和描述
        db: 資料庫會話
        
    Returns:
        DefaultGoogleApiKeyResponse: 設置結果
    """
    current_user = request.state.current_user
    ensure_admin(current_user)
    
    import json
    value = json.dumps({"api_key": body.api_key})
    
    # 檢查設定是否已存在
    stmt = select(settings_table.Table).where(
        settings_table.Table.key == "default_google_api_key"
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    
    if existing:
        existing.value = value
        if body.description:
            existing.description = body.description
        await db.commit()
        await db.refresh(existing)
        return DefaultGoogleApiKeyResponse(
            api_key=body.api_key,
            description=existing.description,
            updated_at=existing.updated_at.isoformat() if existing.updated_at else None
        )
    else:
        new_setting = settings_table.Table(
            key="default_google_api_key",
            value=value,
            description=body.description
        )
        db.add(new_setting)
        await db.commit()
        await db.refresh(new_setting)
        return DefaultGoogleApiKeyResponse(
            api_key=body.api_key,
            description=new_setting.description,
            updated_at=new_setting.updated_at.isoformat() if new_setting.updated_at else None
        )


@admin_router.get("/settings/default-google-api-key", response_model=DefaultGoogleApiKeyResponse)
async def get_default_google_api_key(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """獲取預設 Google API Key（只返回部分字符）"""
    current_user = request.state.current_user
    ensure_admin(current_user)
    
    stmt = select(settings_table.Table).where(
        settings_table.Table.key == "default_google_api_key"
    )
    result = await db.execute(stmt)
    setting = result.scalar_one_or_none()
    
    if setting:
        import json
        value = json.loads(setting.value)
        api_key = value.get("api_key") if isinstance(value, dict) else value
        
        # 遮罩 API Key（只顯示前8個和後8個字符）
        if api_key and len(api_key) > 16:
            masked_key = f"{api_key[:8]}...{api_key[-8:]}"
        else:
            masked_key = "*" * len(api_key) if api_key else None
        
        return DefaultGoogleApiKeyResponse(
            api_key=masked_key,
            description=setting.description,
            updated_at=setting.updated_at.isoformat() if setting.updated_at else None
        )
    else:
        return DefaultGoogleApiKeyResponse(api_key=None, description=None, updated_at=None)


@admin_router.get("/settings/default-llm", response_model=DefaultLLMResponse)
async def get_default_llm(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """獲取系統預設 LLM 供應商與模型（全系統共享，僅管理員可讀寫）"""
    current_user = request.state.current_user
    ensure_admin(current_user)

    import json

    stmt = select(settings_table.Table).where(
        settings_table.Table.key.in_(["default_llm_provider", "default_llm_model"])
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    kv = {r.key: r for r in rows}

    def _parse_value(raw: str | None) -> str | None:
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed.get("value") or parsed.get("provider") or parsed.get("model")
            if isinstance(parsed, str):
                return parsed
            return str(parsed)
        except Exception:
            # 允許直接存純字串
            return raw

    provider = _parse_value(kv.get("default_llm_provider").value if kv.get("default_llm_provider") else None)
    model = _parse_value(kv.get("default_llm_model").value if kv.get("default_llm_model") else None)

    from ...router.User.settings import get_default_user_settings
    default_settings = get_default_user_settings()
    provider = provider or default_settings.default_llm_provider
    model = model or default_settings.default_llm_model

    # description: 取其中一筆（優先 provider 那筆）
    desc = None
    updated_at = None
    if kv.get("default_llm_provider") and kv["default_llm_provider"].description:
        desc = kv["default_llm_provider"].description
    elif kv.get("default_llm_model") and kv["default_llm_model"].description:
        desc = kv["default_llm_model"].description

    # updated_at: 取較新者
    updated_candidates = [
        kv["default_llm_provider"].updated_at if kv.get("default_llm_provider") else None,
        kv["default_llm_model"].updated_at if kv.get("default_llm_model") else None,
    ]
    updated_candidates = [d for d in updated_candidates if d]
    if updated_candidates:
        updated_at = max(updated_candidates).isoformat()

    return DefaultLLMResponse(
        default_llm_provider=provider,
        default_llm_model=model,
        description=desc,
        updated_at=updated_at,
    )


@admin_router.post("/settings/default-llm", response_model=DefaultLLMResponse)
async def set_default_llm(
    request: Request,
    body: SetDefaultLLMDTO,
    db: AsyncSession = Depends(get_session),
):
    """設置系統預設 LLM 供應商與模型（全系統共享，僅管理員可修改）"""
    current_user = request.state.current_user
    ensure_admin(current_user)

    import json

    provider_value = json.dumps({"value": body.default_llm_provider})
    model_value = json.dumps({"value": body.default_llm_model})

    async def _upsert(key: str, value: str):
        stmt = select(settings_table.Table).where(settings_table.Table.key == key)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
            if body.description is not None:
                existing.description = body.description
            return existing
        rec = settings_table.Table(key=key, value=value, description=body.description)
        db.add(rec)
        return rec

    provider_rec = await _upsert("default_llm_provider", provider_value)
    model_rec = await _upsert("default_llm_model", model_value)

    await db.commit()
    await db.refresh(provider_rec)
    await db.refresh(model_rec)

    updated_at = None
    updated_candidates = [provider_rec.updated_at, model_rec.updated_at]
    updated_candidates = [d for d in updated_candidates if d]
    if updated_candidates:
        updated_at = max(updated_candidates).isoformat()

    return DefaultLLMResponse(
        default_llm_provider=body.default_llm_provider,
        default_llm_model=body.default_llm_model,
        description=body.description,
        updated_at=updated_at,
    )


@admin_router.get("/settings/video-params", response_model=VideoParamsResponse)
async def get_video_params(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """取得影片參數設定（目前僅切片長度 segment_seconds）。"""
    current_user = request.state.current_user
    ensure_admin(current_user)

    import json

    stmt = select(settings_table.Table).where(settings_table.Table.key == "video_segment_seconds")
    result = await db.execute(stmt)
    setting = result.scalar_one_or_none()

    # 預設值：30 秒（與 Camera DTO 預設一致）
    segment_seconds = 30
    desc = None
    updated_at = None

    if setting:
        try:
            value = json.loads(setting.value)
            if isinstance(value, dict) and value.get("segment_seconds") is not None:
                segment_seconds = int(value["segment_seconds"])
            elif isinstance(value, (int, float, str)):
                segment_seconds = int(value)
        except Exception:
            # 容忍舊格式/純字串
            try:
                segment_seconds = int(setting.value)
            except Exception:
                pass
        desc = setting.description
        updated_at = setting.updated_at.isoformat() if setting.updated_at else None

    return VideoParamsResponse(
        segment_seconds=int(segment_seconds),
        description=desc,
        updated_at=updated_at,
    )


@admin_router.post("/settings/video-params", response_model=VideoParamsResponse)
async def set_video_params(
    request: Request,
    body: SetVideoParamsDTO,
    db: AsyncSession = Depends(get_session),
):
    """設置影片參數設定（目前僅切片長度 segment_seconds）。"""
    current_user = request.state.current_user
    ensure_admin(current_user)

    # 與 Camera DTO 限制一致
    if body.segment_seconds < 1 or body.segment_seconds > 600:
        raise HTTPException(status_code=400, detail="segment_seconds must be between 1 and 600")

    import json
    value = json.dumps({"segment_seconds": int(body.segment_seconds)})

    stmt = select(settings_table.Table).where(settings_table.Table.key == "video_segment_seconds")
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        existing.value = value
        if body.description is not None:
            existing.description = body.description
        await db.commit()
        await db.refresh(existing)
        return VideoParamsResponse(
            segment_seconds=int(body.segment_seconds),
            description=existing.description,
            updated_at=existing.updated_at.isoformat() if existing.updated_at else None,
        )

    rec = settings_table.Table(key="video_segment_seconds", value=value, description=body.description)
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return VideoParamsResponse(
        segment_seconds=int(body.segment_seconds),
        description=rec.description,
        updated_at=rec.updated_at.isoformat() if rec.updated_at else None,
    )


@admin_router.get("/settings/default-ai-key-limits", response_model=DefaultAiKeyLimitsResponse)
async def get_default_ai_key_limits(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """取得系統預設 AI API Key（預設 key）的用量限制（RPM/RPD，套用在每位使用者使用預設 key 時）。"""
    current_user = request.state.current_user
    ensure_admin(current_user)

    import json

    # 安全預設值（可由管理員覆寫）
    rpm = 10
    rpd = 20
    desc = None
    updated_at = None

    stmt = select(settings_table.Table).where(settings_table.Table.key == "default_ai_key_limits")
    result = await db.execute(stmt)
    setting = result.scalar_one_or_none()

    if setting:
        try:
            value = json.loads(setting.value)
            if isinstance(value, dict):
                if value.get("rpm") is not None:
                    rpm = int(value["rpm"])
                if value.get("rpd") is not None:
                    rpd = int(value["rpd"])
            elif isinstance(value, (list, tuple)) and len(value) >= 2:
                rpm = int(value[0])
                rpd = int(value[1])
        except Exception:
            # 容忍舊格式/純字串
            pass
        desc = setting.description
        updated_at = setting.updated_at.isoformat() if setting.updated_at else None

    return DefaultAiKeyLimitsResponse(rpm=int(rpm), rpd=int(rpd), description=desc, updated_at=updated_at)


@admin_router.post("/settings/default-ai-key-limits", response_model=DefaultAiKeyLimitsResponse)
async def set_default_ai_key_limits(
    request: Request,
    body: SetDefaultAiKeyLimitsDTO,
    db: AsyncSession = Depends(get_session),
):
    """設置系統預設 AI API Key（預設 key）的用量限制（RPM/RPD）。"""
    current_user = request.state.current_user
    ensure_admin(current_user)

    # 合理範圍：避免誤設成極大值導致失控
    if body.rpm < 1 or body.rpm > 300:
        raise HTTPException(status_code=400, detail="rpm must be between 1 and 300")
    if body.rpd < 1 or body.rpd > 10000:
        raise HTTPException(status_code=400, detail="rpd must be between 1 and 10000")

    import json
    value = json.dumps({"rpm": int(body.rpm), "rpd": int(body.rpd)})

    stmt = select(settings_table.Table).where(settings_table.Table.key == "default_ai_key_limits")
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        existing.value = value
        if body.description is not None:
            existing.description = body.description
        await db.commit()
        await db.refresh(existing)
        return DefaultAiKeyLimitsResponse(
            rpm=int(body.rpm),
            rpd=int(body.rpd),
            description=existing.description,
            updated_at=existing.updated_at.isoformat() if existing.updated_at else None,
        )

    rec = settings_table.Table(key="default_ai_key_limits", value=value, description=body.description)
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return DefaultAiKeyLimitsResponse(
        rpm=int(body.rpm),
        rpd=int(body.rpd),
        description=rec.description,
        updated_at=rec.updated_at.isoformat() if rec.updated_at else None,
    )


# ====== 黑名單管理 API ======

@admin_router.post("/blacklist", response_model=BlacklistEntryDTO)
async def add_to_blacklist(
    request: Request,
    body: AddToBlacklistDTO,
    db: AsyncSession = Depends(get_session),
):
    """將使用者添加到黑名單（禁止使用預設 API Key）"""
    current_user = request.state.current_user
    ensure_admin(current_user)
    
    # 檢查使用者是否存在
    stmt = select(users.Table).where(users.Table.id == body.user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="使用者不存在")
    
    # 檢查是否已在黑名單中
    stmt = select(api_key_blacklist.Table).where(
        api_key_blacklist.Table.user_id == body.user_id
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    
    if existing:
        # 已存在：視為更新（允許更新原因），回傳現有條目，避免前端儲存時遇到 400
        if body.reason is not None:
            existing.reason = body.reason
        await db.commit()
        await db.refresh(existing)
        await db.refresh(user)
        return BlacklistEntryDTO(
            user_id=existing.user_id,
            user_account=user.account,
            user_name=user.name,
            reason=existing.reason,
            created_at=existing.created_at.isoformat() if existing.created_at else ""
        )
    
    # 添加到黑名單
    blacklist_entry = api_key_blacklist.Table(
        user_id=body.user_id,
        reason=body.reason
    )
    db.add(blacklist_entry)
    
    # 更新使用者設定，取消使用預設 API Key
    from ...router.User.settings import UserSettings, get_default_user_settings
    if user.settings:
        try:
            user_settings = UserSettings.model_validate(user.settings)
            user_settings.use_default_api_key = False
            user.settings = user_settings.model_dump()
        except Exception:
            pass  # 如果解析失敗，跳過
    
    await db.commit()
    await db.refresh(blacklist_entry)
    await db.refresh(user)
    
    return BlacklistEntryDTO(
        user_id=blacklist_entry.user_id,
        user_account=user.account,
        user_name=user.name,
        reason=blacklist_entry.reason,
        created_at=blacklist_entry.created_at.isoformat() if blacklist_entry.created_at else ""
    )


@admin_router.delete("/blacklist/{user_id}")
async def remove_from_blacklist(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_session),
):
    """從黑名單中移除使用者"""
    current_user = request.state.current_user
    ensure_admin(current_user)
    
    stmt = select(api_key_blacklist.Table).where(
        api_key_blacklist.Table.user_id == user_id
    )
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    
    if not entry:
        raise HTTPException(status_code=404, detail="使用者不在黑名單中")
    
    await db.delete(entry)
    await db.commit()
    
    return {"message": "已從黑名單中移除"}


@admin_router.get("/blacklist", response_model=list[BlacklistEntryDTO])
async def list_blacklist(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """獲取黑名單列表"""
    current_user = request.state.current_user
    ensure_admin(current_user)
    
    stmt = select(api_key_blacklist.Table)
    result = await db.execute(stmt)
    entries = result.scalars().all()
    
    return [
        BlacklistEntryDTO(
            user_id=entry.user_id,
            user_account=entry.user.account,
            user_name=entry.user.name,
            reason=entry.reason,
            created_at=entry.created_at.isoformat() if entry.created_at else ""
        )
        for entry in entries
    ]


# ====== 使用者統計 API ======

@admin_router.get("/users/stats", response_model=list[UserStatsDTO])
async def get_users_stats(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """獲取所有使用者的統計資訊（Token 使用量、聊天訊息數量）"""
    current_user = request.state.current_user
    ensure_admin(current_user)
    
    # 獲取所有使用者
    stmt = select(users.Table).where(users.Table.role == users.Role.user)
    result = await db.execute(stmt)
    all_users = result.scalars().all()

    # 聚合統計：
    # - Token 使用量（chat/diary/compute 全部加總）
    # - 聊天訊息數：依需求「只記錄 LLM 成功回覆次數」，因此只統計 chat source 的 assistant_replies
    from ...DataAccess.tables import llm_usage_logs
    from sqlalchemy import case

    assistant_messages_expr = func.coalesce(llm_usage_logs.Table.assistant_replies, 0)

    usage_stmt = (
        select(
            llm_usage_logs.Table.user_id,
            func.coalesce(func.sum(llm_usage_logs.Table.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(llm_usage_logs.Table.assistant_replies), 0).label("assistant_replies"),
            # 只計 chat source 的 assistant_replies
            func.coalesce(
                func.sum(
                    case(
                        (llm_usage_logs.Table.source == "chat", assistant_messages_expr),
                        else_=0,
                    )
                ),
                0,
            ).label("chat_assistant_messages"),
        )
        .group_by(llm_usage_logs.Table.user_id)
    )
    usage_result = await db.execute(usage_stmt)
    usage_map = {
        int(row.user_id): {
            "total_tokens": int(row.total_tokens or 0),
            "assistant_replies": int(row.assistant_replies or 0),
            "chat_assistant_messages": int(row.chat_assistant_messages or 0),
        }
        for row in usage_result
    }
    
    # 獲取黑名單
    blacklist_stmt = select(api_key_blacklist.Table)
    blacklist_result = await db.execute(blacklist_stmt)
    blacklist_entries = {entry.user_id for entry in blacklist_result.scalars().all()}
    
    # 獲取使用者設定中的 use_default_api_key
    from ...router.User.settings import UserSettings, get_default_user_settings
    
    stats_list = []
    for user in all_users:
        # 檢查是否在黑名單中
        is_blacklisted = user.id in blacklist_entries
        
        # 獲取 use_default_api_key
        use_default_api_key = True
        if user.settings:
            try:
                user_settings = UserSettings.model_validate(user.settings)
                use_default_api_key = user_settings.use_default_api_key
            except Exception:
                pass
        
        totals = usage_map.get(int(user.id), {"total_tokens": 0, "assistant_replies": 0, "chat_assistant_messages": 0})
        total_token_usage = totals["total_tokens"]
        # 聊天訊息數：僅計 LLM 成功回覆次數
        chat_assistant = totals.get("chat_assistant_messages", 0)
        total_chat_messages = int(chat_assistant)
        
        stats_list.append(UserStatsDTO(
            user_id=user.id,
            account=user.account,
            name=user.name,
            total_token_usage=total_token_usage,
            total_chat_messages=total_chat_messages,
            is_blacklisted=is_blacklisted,
            use_default_api_key=use_default_api_key
        ))
    
    return stats_list


@admin_router.get("/users/{user_id}", response_model=UserDetailDTO)
async def get_user_detail(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_session),
):
    """取得單一使用者詳情（僅管理員；包含 password_hash 與黑名單狀態）。"""
    current_user = request.state.current_user
    ensure_admin(current_user)

    # 取得使用者
    stmt = select(users.Table).where(users.Table.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="使用者不存在")

    # 黑名單條目（可為 None）
    bl_stmt = select(api_key_blacklist.Table).where(api_key_blacklist.Table.user_id == user_id)
    bl_res = await db.execute(bl_stmt)
    bl = bl_res.scalar_one_or_none()

    created_at = getattr(user, "created_at", None)
    updated_at = getattr(user, "updated_at", None)

    return UserDetailDTO(
        user_id=int(user.id),
        account=str(user.account),
        name=str(user.name),
        role=str(getattr(user.role, "value", user.role)),
        gender=str(getattr(user.gender, "value", user.gender)),
        birthday=user.birthday.isoformat() if getattr(user, "birthday", None) else None,
        phone=str(user.phone),
        email=str(user.email),
        headshot_url=getattr(user, "headshot_url", None),
        password_hash=str(getattr(user, "password_hash", "")),
        active=bool(getattr(user, "active", True)),
        settings=getattr(user, "settings", None),
        is_blacklisted=bool(bl is not None),
        blacklist_reason=getattr(bl, "reason", None) if bl else None,
        created_at=created_at.isoformat() if created_at else None,
        updated_at=updated_at.isoformat() if updated_at else None,
    )


@admin_router.patch("/users/{user_id}", response_model=UserDetailDTO)
async def update_user_active(
    request: Request,
    user_id: int,
    body: UpdateUserActiveDTO,
    db: AsyncSession = Depends(get_session),
):
    """更新使用者帳號啟用狀態（僅管理員）。"""
    current_user = request.state.current_user
    ensure_admin(current_user)

    stmt = select(users.Table).where(users.Table.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="使用者不存在")

    user.active = bool(body.active)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # 黑名單條目（可為 None）
    bl_stmt = select(api_key_blacklist.Table).where(api_key_blacklist.Table.user_id == user_id)
    bl_res = await db.execute(bl_stmt)
    bl = bl_res.scalar_one_or_none()

    created_at = getattr(user, "created_at", None)
    updated_at = getattr(user, "updated_at", None)

    return UserDetailDTO(
        user_id=int(user.id),
        account=str(user.account),
        name=str(user.name),
        role=str(getattr(user.role, "value", user.role)),
        gender=str(getattr(user.gender, "value", user.gender)),
        birthday=user.birthday.isoformat() if getattr(user, "birthday", None) else None,
        phone=str(user.phone),
        email=str(user.email),
        headshot_url=getattr(user, "headshot_url", None),
        password_hash=str(getattr(user, "password_hash", "")),
        active=bool(getattr(user, "active", True)),
        settings=getattr(user, "settings", None),
        is_blacklisted=bool(bl is not None),
        blacklist_reason=getattr(bl, "reason", None) if bl else None,
        created_at=created_at.isoformat() if created_at else None,
        updated_at=updated_at.isoformat() if updated_at else None,
    )


# ====== 任務列表 API ======

@admin_router.get("/tasks", response_model=TaskListRespDTO)
async def get_tasks(
    request: Request,
    status_filter: Optional[str] = None,
    task_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
):
    """獲取所有任務列表（整合 compute 和 streaming 服務）。
    
    Args:
        request: FastAPI Request 對象
        status_filter: 可選的狀態過濾（pending, processing, running, success, failed, error, stopped, reconnecting）
        task_type: 可選的任務類型過濾（video_description, vlog_generation, diary_generation, streaming）
        page: 頁碼（從 1 開始）
        size: 每頁筆數
        db: 資料庫會話
        
    Returns:
        TaskListRespDTO: 任務列表和分頁資訊
    """
    current_user = request.state.current_user
    ensure_admin(current_user)
    
    import httpx
    import os
    from ...DataAccess.tables import inference_jobs
    from ...DataAccess.tables.__Enumeration import JobStatus
    
    tasks = []
    
    # 獲取 Compute Server 的任務（從 inference_jobs 表格）
    job_conditions = []
    
    # 狀態過濾：只處理 Compute Server 的狀態（pending, processing, success, failed）
    compute_statuses = ["pending", "processing", "success", "failed"]
    if status_filter:
        if status_filter in compute_statuses:
            try:
                job_status = JobStatus(status_filter)
                job_conditions.append(inference_jobs.Table.status == job_status)
            except ValueError:
                pass  # 忽略無效的狀態過濾
        # 如果 status_filter 是 Streaming Server 的狀態，則不查詢 Compute Server 的任務
        elif status_filter in ["running", "starting", "stopped", "error", "reconnecting"]:
            # 跳過 Compute Server 的查詢
            pass
        # 如果 status_filter 不在任何已知狀態中，也不查詢
    
    # 任務類型過濾：只處理 Compute Server 的任務類型
    if task_type and task_type != "streaming":
        # 映射任務類型
        type_mapping = {
            "video_description": "video_description_extraction",
            "vlog_generation": "vlog_generation",
            "diary_generation": "diary_generation",
            # 其他 compute 背景任務
            "embedding_generation": "embedding_generation",
            "diary_embeddings": "diary_embeddings",
            "rag_highlights": "rag_highlights",
        }
        if task_type in type_mapping:
            job_conditions.append(inference_jobs.Table.type == type_mapping[task_type])
        # 如果 task_type 不在映射中，不添加條件（查詢所有類型）
    
    stmt = select(inference_jobs.Table)
    if job_conditions:
        stmt = stmt.where(and_(*job_conditions))
    stmt = stmt.order_by(inference_jobs.Table.created_at.desc())
    
    result = await db.execute(stmt)
    jobs = result.scalars().all()
    
    for job in jobs:
        # 映射任務類型
        task_type_mapped = {
            "video_description_extraction": "video_description",
            "vlog_generation": "vlog_generation",
            "diary_generation": "diary_generation",
            "embedding_generation": "embedding_generation",
            "diary_embeddings": "diary_embeddings",
            "rag_highlights": "rag_highlights",
        }.get(job.type, job.type)
        
        # 獲取進度（如果有）
        progress = None
        if job.params and isinstance(job.params, dict):
            progress = job.params.get("progress")
        
        user_id = None
        if job.params and isinstance(job.params, dict):
            user_id = job.params.get("user_id")
        
        tasks.append(TaskInfoDTO(
            task_id=str(job.id),
            task_type=task_type_mapped,
            status=job.status.value if hasattr(job.status, "value") else str(job.status),
            user_id=user_id,
            camera_id=str(job.params.get("camera_id")) if job.params and isinstance(job.params, dict) and job.params.get("camera_id") else None,
            created_at=job.created_at.isoformat() if job.created_at else None,
            updated_at=job.updated_at.isoformat() if job.updated_at else None,
            progress=progress,
            error_message=job.error_message,
            details={
                "type": job.type,
                "input_type": job.input_type,
                "input_url": job.input_url,
                "output_url": job.output_url,
                "trace_id": job.trace_id,
                "duration": job.duration,
                "error_code": job.error_code,
                "metrics": job.metrics,
            }
        ))
    
    # 獲取 Streaming Server 的任務
    streaming_base = os.getenv("STREAMING_BASE", "http://streaming:30500")
    streaming_token = os.getenv("INTERNAL_TOKEN", "")
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{streaming_base}/streams",
                headers={"X-Internal-Token": streaming_token} if streaming_token else {}
            )
            if response.status_code == 200:
                streams = response.json()
                for stream in streams:
                    # 狀態過濾：只處理 Streaming Server 的狀態
                    streaming_statuses = ["running", "starting", "stopped", "error", "reconnecting"]
                    if status_filter:
                        if status_filter in streaming_statuses:
                            # 如果狀態匹配，檢查是否與 stream 的狀態一致
                            if stream.get("status") != status_filter:
                                continue
                        else:
                            # 如果 status_filter 是 Compute Server 的狀態，跳過所有 Streaming 任務
                            continue
                    
                    # 任務類型過濾：只處理 streaming 類型
                    if task_type and task_type != "streaming":
                        continue
                    
                    tasks.append(TaskInfoDTO(
                        task_id=stream.get("stream_id", ""),
                        task_type="streaming",
                        status=stream.get("status", "stopped"),
                        user_id=int(stream.get("user_id")) if stream.get("user_id") else None,
                        camera_id=stream.get("camera_id"),
                        created_at=None,  # Streaming Server 沒有提供創建時間
                        updated_at=None,
                        progress=None,
                        error_message=stream.get("error_message"),
                        details={
                            "input_url": stream.get("input_url"),
                            "record_dir": stream.get("record_dir"),
                            "segment_seconds": stream.get("segment_seconds"),
                            "pid": stream.get("pid"),
                            "cmdline": stream.get("cmdline"),
                        }
                    ))
    except Exception as e:
        print(f"[Admin] 獲取 Streaming Server 任務失敗: {str(e)}")
        # 繼續執行，不影響其他任務
    
    # 按創建時間排序（最新的在前）
    # 對於沒有 created_at 的任務（Streaming Server），使用 updated_at 或排到最後
    def sort_key(task: TaskInfoDTO) -> tuple:
        # 返回 (has_created_at, timestamp) 元組，確保有時間戳的排在前面
        if task.created_at:
            return (1, task.created_at)
        elif task.updated_at:
            return (1, task.updated_at)
        else:
            return (0, "")
    
    tasks.sort(key=sort_key, reverse=True)
    
    # 分頁處理
    total = len(tasks)
    page_total = (total + size - 1) // size if total > 0 else 1
    start_idx = (page - 1) * size
    end_idx = start_idx + size
    paginated_items = tasks[start_idx:end_idx]
    
    return TaskListRespDTO(
        items=paginated_items,
        item_total=total,
        page_size=size,
        page_now=page,
        page_total=page_total
    )
