# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional
import traceback

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError

from ...DataAccess.Connect import get_session
from ...DataAccess.tables import users
from ...security.jwt_manager import JWTManager
from .DTO import (
    SignupRequestDTO,
    LoginRequestDTO,
    LoginResponseDTO,
    ChangePasswordRequestDTO,
    UpdateUserProfileDTO,
)
from .settings import (
    UserSettings,
    UpdateUserSettingsRequest,
    UserSettingsResponse,
    get_default_user_settings,
)

WWW_BEARER = {"WWW-Authenticate": "Bearer"}


# ======= Service（商業邏輯）=======
class UserService:
    """使用者註冊 / 登入 / 修改資料 / 修改密碼 的應用服務。"""

    def __init__(self, jwt_manager: Optional[JWTManager] = None):
        self.jwt = jwt_manager or JWTManager()

    # 註冊：成功直接回 access token
    async def signup_user(self, db: AsyncSession, body: SignupRequestDTO) -> LoginResponseDTO:
        try:
            # 檢查 account
            stmt = select(users.Table).where(users.Table.account == body.account)
            exists = await db.execute(stmt)
            if exists.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="帳號已存在")

            # 檢查 email
            stmt = select(users.Table).where(users.Table.email == body.email)
            exists = await db.execute(stmt)
            if exists.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Email 已被使用")
            
            # 檢查 phone
            stmt = select(users.Table).where(users.Table.phone == body.phone)
            exists = await db.execute(stmt)
            if exists.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="phone 已被使用")
            
            hashed = self.jwt.hash_password(body.password)
            # 創建預設使用者設定
            default_settings = get_default_user_settings()
            
            user = users.Table(
                account=body.account,
                name=body.name,
                gender=body.gender,
                birthday=body.birthday,
                phone=body.phone,
                email=body.email,
                headshot_url=body.headshot_url,
                password_hash=hashed,
                role=users.Role.user,
                active=True,
                settings=default_settings.model_dump()
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

            token = self._issue_token(user)
            return LoginResponseDTO(access_token=token)
            
        except HTTPException:
            # 已經是 HTTPException，直接重新拋出
            await db.rollback()
            raise
        except IntegrityError as e:
            # 資料庫唯一性約束錯誤（備用檢查）
            await db.rollback()
            print(f"[DB Integrity Error] signup_user: {str(e)}")
            raise HTTPException(status_code=400, detail="帳號、Email 或電話號碼已被使用")
        except OperationalError as e:
            # 資料庫連接或操作錯誤
            await db.rollback()
            print(f"[DB Operational Error] signup_user: {str(e)}")
            raise HTTPException(status_code=503, detail="資料庫服務暫時無法使用，請稍後再試")
        except SQLAlchemyError as e:
            # 其他資料庫錯誤
            await db.rollback()
            print(f"[DB Error] signup_user: {str(e)}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail="註冊過程中發生錯誤，請稍後再試")
        except Exception as e:
            # 未預期的錯誤
            await db.rollback()
            print(f"[Unexpected Error] signup_user: {str(e)}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail="註冊失敗，請聯繫系統管理員")
    
    async def signup_admin(self, db: AsyncSession, body: SignupRequestDTO) -> LoginResponseDTO:
        try:
            # 檢查 account
            stmt = select(users.Table).where(users.Table.account == body.account)
            exists = await db.execute(stmt)
            if exists.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="帳號已存在")

            # 檢查 email
            stmt = select(users.Table).where(users.Table.email == body.email)
            exists = await db.execute(stmt)
            if exists.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Email 已被使用")
            # 檢查 phone
            stmt = select(users.Table).where(users.Table.phone == body.phone)
            exists = await db.execute(stmt)
            if exists.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="phone 已被使用")
            
            hashed = self.jwt.hash_password(body.password)
            # 創建預設使用者設定
            default_settings = get_default_user_settings()
            
            user = users.Table(
                account=body.account,
                name=body.name,
                gender=body.gender,
                birthday=body.birthday,
                phone=body.phone,
                email=body.email,
                password_hash=hashed,
                headshot_url=body.headshot_url,
                role=users.Role.admin,
                active=True,
                settings=default_settings.model_dump()
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

            token = self._issue_token(user)
            return LoginResponseDTO(access_token=token)
            
        except HTTPException:
            await db.rollback()
            raise
        except IntegrityError as e:
            await db.rollback()
            print(f"[DB Integrity Error] signup_admin: {str(e)}")
            raise HTTPException(status_code=400, detail="帳號、Email 或電話號碼已被使用")
        except OperationalError as e:
            await db.rollback()
            print(f"[DB Operational Error] signup_admin: {str(e)}")
            raise HTTPException(status_code=503, detail="資料庫服務暫時無法使用，請稍後再試")
        except SQLAlchemyError as e:
            await db.rollback()
            print(f"[DB Error] signup_admin: {str(e)}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail="註冊管理員過程中發生錯誤，請稍後再試")
        except Exception as e:
            await db.rollback()
            print(f"[Unexpected Error] signup_admin: {str(e)}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail="註冊失敗，請聯繫系統管理員")
    # 登入
    async def login_user(self, db: AsyncSession, body: LoginRequestDTO) -> LoginResponseDTO:
        try:
            stmt = select(users.Table).where(users.Table.account == body.account)
            result = await db.execute(stmt)
            user: Optional[users.Table] = result.scalar_one_or_none()

            if not user or not self.jwt.verify_password(body.password, user.password_hash):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="帳號或密碼錯誤",
                    headers=WWW_BEARER,
                )
            
            if not user.active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="帳號已停用",
                    headers=WWW_BEARER,
                )

            token = self._issue_token(user)
            return LoginResponseDTO(access_token=token)
            
        except HTTPException:
            # 已經是 HTTPException，直接重新拋出
            raise
        except OperationalError as e:
            # 資料庫連接錯誤
            print(f"[DB Operational Error] login_user: {str(e)}")
            raise HTTPException(status_code=503, detail="資料庫服務暫時無法使用，請稍後再試")
        except SQLAlchemyError as e:
            # 資料庫查詢錯誤
            print(f"[DB Error] login_user: {str(e)}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail="登入過程中發生錯誤，請稍後再試")
        except Exception as e:
            # JWT 生成錯誤或其他未預期錯誤
            print(f"[Unexpected Error] login_user: {str(e)}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail="登入失敗，請稍後再試")

    # 修改基本資料（不含密碼）
    async def update_profile(
        self, db: AsyncSession, current_user: users.Table, body: UpdateUserProfileDTO
    ) -> dict:
        try:
            patch = body.model_dump(exclude_unset=True)

            # 檢查 email 唯一性
            new_email = patch.get("email")
            if new_email and new_email != current_user.email:
                stmt = (
                    select(users.Table)
                    .where(users.Table.email == new_email)
                    .where(users.Table.id != current_user.id)
                )
                exists = await db.execute(stmt)
                if exists.scalar_one_or_none():
                    raise HTTPException(status_code=400, detail="Email 已被使用")

            for k, v in patch.items():
                setattr(current_user, k, v)

            db.add(current_user)
            await db.commit()
            await db.refresh(current_user)

            return {"msg": "資料已更新", "user": self._public_user(current_user)}
            
        except HTTPException:
            await db.rollback()
            raise
        except IntegrityError as e:
            await db.rollback()
            print(f"[DB Integrity Error] update_profile: {str(e)}")
            raise HTTPException(status_code=400, detail="Email 或電話號碼已被使用")
        except OperationalError as e:
            await db.rollback()
            print(f"[DB Operational Error] update_profile: {str(e)}")
            raise HTTPException(status_code=503, detail="資料庫服務暫時無法使用，請稍後再試")
        except SQLAlchemyError as e:
            await db.rollback()
            print(f"[DB Error] update_profile: {str(e)}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail="更新資料過程中發生錯誤，請稍後再試")
        except Exception as e:
            await db.rollback()
            print(f"[Unexpected Error] update_profile: {str(e)}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail="更新資料失敗，請稍後再試")

    # 修改密碼
    async def change_password(
        self, db: AsyncSession, current_user: users.Table, body: ChangePasswordRequestDTO
    ) -> dict:
        try:
            if not self.jwt.verify_password(body.old_password, current_user.password_hash):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="舊密碼不正確",
                    headers=WWW_BEARER,
                )
            new_hashed = self.jwt.hash_password(body.new_password)
            current_user.password_hash = new_hashed

            db.add(current_user)
            await db.commit()
            return {"msg": "密碼已成功更新"}
            
        except HTTPException:
            await db.rollback()
            raise
        except OperationalError as e:
            await db.rollback()
            print(f"[DB Operational Error] change_password: {str(e)}")
            raise HTTPException(status_code=503, detail="資料庫服務暫時無法使用，請稍後再試")
        except SQLAlchemyError as e:
            await db.rollback()
            print(f"[DB Error] change_password: {str(e)}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail="修改密碼過程中發生錯誤，請稍後再試")
        except Exception as e:
            await db.rollback()
            print(f"[Unexpected Error] change_password: {str(e)}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail="修改密碼失敗，請稍後再試")

    # ---- internal helpers ----
    def _issue_token(self, user: users.Table) -> str:
        return self.jwt.create_token(
            subject=str(user.id),
            extra={"account": user.account, "role": user.role},
        )

    # 獲取使用者設定
    async def get_user_settings(self, db: AsyncSession, current_user: users.Table) -> UserSettings:
        """獲取使用者設定"""
        try:
            if current_user.settings:
                return UserSettings.model_validate(current_user.settings)
            else:
                # 如果沒有設定，返回預設設定
                return get_default_user_settings()
        except Exception as e:
            print(f"[Error] get_user_settings: {str(e)}")
            # 如果解析失敗，返回預設設定
            return get_default_user_settings()
    
    # 更新使用者設定
    async def update_user_settings(
        self, 
        db: AsyncSession, 
        current_user: users.Table, 
        body: UpdateUserSettingsRequest
    ) -> UserSettingsResponse:
        """更新使用者設定"""
        try:
            # 獲取現有設定
            current_settings = await self.get_user_settings(db, current_user)
            
            # 更新設定
            update_data = body.model_dump(exclude_unset=True)
            
            # 更新基本設定
            if "timezone" in update_data:
                current_settings.timezone = update_data["timezone"]
            if "language" in update_data:
                current_settings.language = update_data["language"]
            if "theme" in update_data:
                current_settings.theme = update_data["theme"]
            if "notifications_enabled" in update_data:
                current_settings.notifications_enabled = update_data["notifications_enabled"]
            if "default_llm_provider" in update_data:
                current_settings.default_llm_provider = update_data["default_llm_provider"]
            if "default_llm_model" in update_data:
                current_settings.default_llm_model = update_data["default_llm_model"]
            if "diary_auto_refresh_enabled" in update_data:
                current_settings.diary_auto_refresh_enabled = update_data["diary_auto_refresh_enabled"]
            if "diary_auto_refresh_interval_minutes" in update_data:
                current_settings.diary_auto_refresh_interval_minutes = update_data["diary_auto_refresh_interval_minutes"]
            if "default_stream_ttl" in update_data:
                current_settings.default_stream_ttl = update_data["default_stream_ttl"]
            if "use_default_api_key" in update_data:
                # 檢查是否在黑名單中
                from ...DataAccess.tables import api_key_blacklist
                stmt = select(api_key_blacklist.Table).where(
                    api_key_blacklist.Table.user_id == current_user.id
                )
                result = await db.execute(stmt)
                is_blacklisted = result.scalar_one_or_none() is not None
                
                # 如果在黑名單中，不能使用預設 API Key
                if is_blacklisted and update_data["use_default_api_key"]:
                    raise HTTPException(
                        status_code=400,
                        detail="您已被禁止使用預設 API Key，請設定您自己的 API Key"
                    )
                
                current_settings.use_default_api_key = update_data["use_default_api_key"]
            
            # 更新 LLM 供應商設定
            # 支持兩種格式：llm_providers 或 llm_model_api.providers
            providers_to_update = None
            if "llm_providers" in update_data:
                providers_to_update = update_data["llm_providers"]
            elif "llm_model_api" in update_data and isinstance(update_data["llm_model_api"], dict):
                providers_to_update = update_data["llm_model_api"].get("providers")
            
            if providers_to_update:
                from .settings import LLMProviderConfig
                for provider_name, provider_data in providers_to_update.items():
                    if isinstance(provider_data, dict):
                        api_key = provider_data.get("api_key", "")
                        if api_key is not None:
                            api_key = str(api_key).strip()
                        
                        # 如果 API key 為空字串或 None，移除該供應商
                        if not api_key:
                            current_settings.llm_model_api.remove_provider(provider_name)
                            continue
                        
                        # 如果只有 api_key，需要保留現有的 model_names
                        existing_provider = current_settings.llm_model_api.get_provider_config(provider_name)
                        model_names = provider_data.get("model_names")
                        
                        # 如果沒有提供 model_names，嘗試保留現有的
                        if model_names is None or (isinstance(model_names, list) and len(model_names) == 0):
                            if existing_provider and existing_provider.model_names:
                                model_names = existing_provider.model_names
                            else:
                                # 如果沒有現有的 model_names，使用空陣列（允許稍後再設定）
                                model_names = []
                        
                        try:
                            provider_config = LLMProviderConfig(
                                api_key=api_key,
                                model_names=model_names if isinstance(model_names, list) else []
                            )
                            current_settings.llm_model_api.add_provider(provider_name, provider_config)
                        except Exception as e:
                            print(f"[Error] 無法創建供應商配置 {provider_name}: {str(e)}")
                            # 繼續處理其他供應商
                            continue
            
            # 檢查是否有 LLM 相關設定變更（需要清除模型實例）
            llm_config_changed = False
            if ("default_llm_provider" in update_data or 
                "default_llm_model" in update_data or 
                providers_to_update):
                llm_config_changed = True
            
            # 儲存到資料庫
            current_user.settings = current_settings.model_dump()
            db.add(current_user)
            await db.commit()
            await db.refresh(current_user)
            
            # 如果 LLM 配置變更，清除該用戶的模型實例
            if llm_config_changed:
                try:
                    from ...router.Chat.llm_tools import user_llm_manager
                    user_llm_manager.force_cleanup_user(current_user.id)
                    print(f"[User Settings] 已清除使用者 {current_user.id} 的 LLM 模型實例（配置已變更）")
                except Exception as e:
                    # 清除失敗不影響設定更新
                    print(f"[User Settings] 清除模型實例時發生錯誤: {str(e)}")
            
            return UserSettingsResponse(
                settings=current_settings,
                message="設定已成功更新"
            )
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            print(f"[Error] update_user_settings: {str(e)}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail="更新設定失敗，請稍後再試")
    
    # 獲取使用者時區
    def get_user_stream_ttl(self, current_user: users.Table) -> int:
        """獲取使用者預設串流 TTL（秒）"""
        try:
            if current_user.settings:
                settings = UserSettings.model_validate(current_user.settings)
                return settings.default_stream_ttl
            else:
                default_settings = get_default_user_settings()
                return default_settings.default_stream_ttl
        except Exception:
            default_settings = get_default_user_settings()
            return default_settings.default_stream_ttl
    
    def get_user_timezone(self, current_user: users.Table) -> str:
        """獲取使用者時區"""
        try:
            if current_user.settings:
                settings = UserSettings.model_validate(current_user.settings)
                return settings.timezone
            else:
                return "Asia/Taipei"  # 預設時區
        except Exception:
            return "Asia/Taipei"  # 預設時區
    
    # 獲取使用者 LLM 設定
    async def get_user_llm_config(self, db: AsyncSession, current_user: users.Table) -> tuple[str, str, Optional[str]]:
        """獲取使用者 LLM 設定 (provider, model, api_key)
        
        會檢查：
        1. 使用者是否在黑名單中（禁止使用預設 API Key）
        2. 使用者是否選擇使用預設 API Key
        3. 如果使用預設 API Key，從系統設定中讀取
        """
        from ...DataAccess.tables import api_key_blacklist
        
        # 檢查是否在黑名單中
        is_blacklisted = False
        try:
            stmt = select(api_key_blacklist.Table).where(
                api_key_blacklist.Table.user_id == current_user.id
            )
            result = await db.execute(stmt)
            blacklist_entry = result.scalar_one_or_none()
            is_blacklisted = blacklist_entry is not None
        except Exception as e:
            print(f"[Error] 檢查黑名單失敗: {str(e)}")
        
        async def _get_system_default_llm() -> tuple[str, str]:
            """從 settings 表取得全系統預設 LLM (provider, model)；若未設定則回傳系統內建預設。"""
            from ...DataAccess.tables import settings as settings_table
            import json
            from .settings import get_default_user_settings

            default_settings = get_default_user_settings()
            provider = default_settings.default_llm_provider
            model = default_settings.default_llm_model

            try:
                stmt = select(settings_table.Table).where(
                    settings_table.Table.key.in_(["default_llm_provider", "default_llm_model"])
                )
                result = await db.execute(stmt)
                rows = result.scalars().all()
                settings_dict = {s.key: s.value for s in rows}

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
                        return raw

                provider_val = _parse_value(settings_dict.get("default_llm_provider"))
                model_val = _parse_value(settings_dict.get("default_llm_model"))
                if provider_val:
                    provider = provider_val
                if model_val:
                    model = model_val
            except Exception as e:
                print(f"[Error] 讀取系統預設 LLM 失敗: {str(e)}")

            return provider, model

        # 獲取使用者設定
        use_default_api_key = True
        try:
            if current_user.settings:
                settings = UserSettings.model_validate(current_user.settings)
                use_default_api_key = settings.use_default_api_key
                
                # 如果在黑名單中，強制取消使用預設 API Key
                if is_blacklisted and use_default_api_key:
                    # 更新使用者設定，取消勾選
                    settings.use_default_api_key = False
                    current_user.settings = settings.model_dump()
                    try:
                        await db.commit()
                    except Exception as commit_error:
                        print(f"[Error] 更新使用者設定失敗: {str(commit_error)}")
                        await db.rollback()
                    use_default_api_key = False
                
                # 若使用者勾選使用系統預設 API Key，則 provider/model 必須強制使用系統預設值
                if use_default_api_key and not is_blacklisted:
                    sys_provider, sys_model = await _get_system_default_llm()
                    return sys_provider, sys_model, None

                return settings.get_llm_config(
                    use_default_api_key=use_default_api_key,
                    is_blacklisted=is_blacklisted,
                )
            else:
                # 使用預設設定
                default_settings = get_default_user_settings()
                # 如果在黑名單中，不能使用預設 API Key
                if is_blacklisted:
                    default_settings.use_default_api_key = False
                # 未登入者也同樣遵守系統預設 provider/model
                if default_settings.use_default_api_key and not is_blacklisted:
                    sys_provider, sys_model = await _get_system_default_llm()
                    return sys_provider, sys_model, None

                return default_settings.get_llm_config(
                    use_default_api_key=default_settings.use_default_api_key,
                    is_blacklisted=is_blacklisted,
                )
        except Exception as e:
            print(f"[Error] 解析使用者設定失敗: {str(e)}")
            # 如果解析失敗，使用預設設定
            default_settings = get_default_user_settings()
            if is_blacklisted:
                default_settings.use_default_api_key = False
            if default_settings.use_default_api_key and not is_blacklisted:
                sys_provider, sys_model = await _get_system_default_llm()
                return sys_provider, sys_model, None

            return default_settings.get_llm_config(
                use_default_api_key=default_settings.use_default_api_key,
                is_blacklisted=is_blacklisted,
            )
    
    async def get_default_google_api_key(self, db: AsyncSession) -> Optional[str]:
        """從系統設定中獲取預設 Google API Key"""
        from ...DataAccess.tables import settings as settings_table
        
        try:
            stmt = select(settings_table.Table).where(
                settings_table.Table.key == "default_google_api_key"
            )
            result = await db.execute(stmt)
            setting = result.scalar_one_or_none()
            if setting:
                import json
                value = json.loads(setting.value)
                return value.get("api_key") if isinstance(value, dict) else value
        except Exception as e:
            print(f"[Error] 讀取預設 Google API Key 失敗: {str(e)}")
        
        # 資料庫中沒有就回傳 None（不再從環境變數讀取）
        return None

    @staticmethod
    def _public_user(u: users.Table) -> dict:
        return {
            "id": u.id,
            "account": u.account,
            "name": u.name,
            "gender": u.gender,
            "birthday": u.birthday,
            "phone": u.phone,
            "email": u.email,
            "role": u.role,
            "headshot_url": u.headshot_url
        }


# ======= Routers =======
from ...config.path import (USER_PREFIX,
                           USER_GET_ME,
                           USER_PATCH_ME,
                           USER_PUT_ME_PASSWORD)

user_router = APIRouter(prefix=USER_PREFIX, tags=["users"])
service = UserService()

@user_router.get(USER_GET_ME)
async def read_me(request: Request):
    try:
        current_user = request.state.current_user
        return {"user": service._public_user(current_user)}
    except AttributeError as e:
        # current_user 不存在（理論上不應發生，因為有 dependency）
        print(f"[Error] read_me: current_user not found - {str(e)}")
        raise HTTPException(status_code=401, detail="未授權的請求")
    except Exception as e:
        print(f"[Unexpected Error] read_me: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="獲取用戶資料失敗")


@user_router.patch(USER_PATCH_ME)
async def update_me(
    request: Request,
    body: UpdateUserProfileDTO,
    db: AsyncSession = Depends(get_session),
    
):
    try:
        current_user = request.state.current_user
        return await service.update_profile(db, current_user, body)
    except HTTPException:
        # Service 層已處理的 HTTPException，直接重新拋出
        raise
    except Exception as e:
        print(f"[Unexpected Error] update_me endpoint: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="更新用戶資料失敗")


@user_router.put(USER_PUT_ME_PASSWORD)
async def change_password(
    request: Request,
    body: ChangePasswordRequestDTO,
    db: AsyncSession = Depends(get_session),
):
    try:
        current_user = request.state.current_user
        return await service.change_password(db, current_user, body)
    except HTTPException:
        # Service 層已處理的 HTTPException，直接重新拋出
        raise
    except Exception as e:
        print(f"[Unexpected Error] change_password endpoint: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="修改密碼失敗")

@user_router.get("/token/refresh", response_model=LoginResponseDTO)
async def refresh_token(request: Request):
    """重新申請個人JWT Token"""
    try:
        current_user = request.state.current_user
        token = service._issue_token(current_user)
        return LoginResponseDTO(access_token=token)
    except AttributeError as e:
        print(f"[Error] refresh_token: current_user not found - {str(e)}")
        raise HTTPException(status_code=401, detail="未授權的請求")
    except Exception as e:
        print(f"[Unexpected Error] refresh_token: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="刷新 Token 失敗")


# ====== 設定相關端點 ======

@user_router.get("/settings", response_model=UserSettingsResponse)
async def get_user_settings(request: Request, db: AsyncSession = Depends(get_session)):
    """獲取使用者設定"""
    try:
        current_user = request.state.current_user
        settings = await service.get_user_settings(db, current_user)
        return UserSettingsResponse(settings=settings, message="設定獲取成功")
    except Exception as e:
        print(f"[Unexpected Error] get_user_settings endpoint: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="獲取設定失敗")


@user_router.patch("/settings", response_model=UserSettingsResponse)
async def update_user_settings(
    request: Request,
    body: UpdateUserSettingsRequest,
    db: AsyncSession = Depends(get_session),
):
    """更新使用者設定"""
    try:
        current_user = request.state.current_user
        return await service.update_user_settings(db, current_user, body)
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Unexpected Error] update_user_settings endpoint: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="更新設定失敗")


@user_router.get("/settings/timezones")
async def get_available_timezones():
    """獲取可用時區列表"""
    try:
        from .settings import get_common_timezones
        return {"timezones": get_common_timezones()}
    except Exception as e:
        print(f"[Unexpected Error] get_available_timezones: {str(e)}")
        raise HTTPException(status_code=500, detail="獲取時區列表失敗")


@user_router.get("/settings/system-default-llm")
async def get_system_default_llm(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    """獲取系統預設的 LLM provider 和 model（供使用者查看）
    
    優先順序：
    1. 從 settings 表獲取（如果管理員已設定）
    2. 使用系統預設值
    """
    try:
        from ...DataAccess.tables import settings as settings_table
        from .settings import get_default_user_settings
        
        # 優先從 settings 表獲取系統預設值
        stmt = select(settings_table.Table).where(
            settings_table.Table.key.in_(["default_llm_provider", "default_llm_model"])
        )
        result = await db.execute(stmt)
        settings_dict = {s.key: s.value for s in result.scalars().all()}
        
        default_settings = get_default_user_settings()
        
        # 解析 provider
        provider = default_settings.default_llm_provider
        if "default_llm_provider" in settings_dict:
            import json
            try:
                value = settings_dict["default_llm_provider"]
                if isinstance(value, str):
                    parsed = json.loads(value)
                    if isinstance(parsed, dict):
                        provider = parsed.get("provider") or parsed.get("value") or provider
                    else:
                        provider = parsed
                else:
                    provider = value
            except:
                pass
        
        # 解析 model
        model = default_settings.default_llm_model
        if "default_llm_model" in settings_dict:
            import json
            try:
                value = settings_dict["default_llm_model"]
                if isinstance(value, str):
                    parsed = json.loads(value)
                    if isinstance(parsed, dict):
                        model = parsed.get("model") or parsed.get("value") or model
                    else:
                        model = parsed
                else:
                    model = value
            except:
                pass

        return {
            "default_llm_provider": provider,
            "default_llm_model": model
        }
    except Exception as e:
        print(f"[Unexpected Error] get_system_default_llm: {str(e)}")
        traceback.print_exc()
        # 如果出錯，返回預設值
        from .settings import get_default_user_settings
        default_settings = get_default_user_settings()
        return {
            "default_llm_provider": default_settings.default_llm_provider,
            "default_llm_model": default_settings.default_llm_model
        }
