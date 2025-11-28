# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import secrets
from typing import Optional, Callable, Awaitable, Tuple, Iterable, Literal, Dict, TypedDict
from uuid import UUID as UUID_t

from fastapi import Security, HTTPException, status, Request, Depends, Query
from fastapi.security import APIKeyHeader
from sqlalchemy import select, update  # ✅ 我補上 update，用於無 ORM 的寫入
from sqlalchemy.ext.asyncio import AsyncSession

from ..DataAccess.Connect import get_session
from ..DataAccess.tables import api_keys, users


# 我定義一個 TypedDict，專門做快取／傳遞純量欄位，避免跨請求持有 ORM 物件
class ApiKeyPublic(TypedDict):
    id: str | int
    owner_id: int
    scopes: list[str]
    active: bool


@dataclass(slots=True)
class APIKeyManagerConfig:
    header_name: str = "X-API-Key"
    show_token_once: bool = True
    # 允許的 scopes（先用固定集合）
    allowed_scopes: set[str] = field(default_factory=lambda: {
        "uploader",   # 允許呼叫 /jobs 建任務
        "compute",    # 允許呼叫 /jobs/{id}/complete 回報
        "mediamtx",   # 允許呼叫 /m2m/streams/auth
        "streaming"  # 允許呼叫 /m2m/streams
    })


class APIKeyManager:
    """
    管理 API Key：產生、雜湊、建立、驗證、旋轉、啟停、查詢 + scopes。
    """

    def __init__(self, config: Optional[APIKeyManagerConfig] = None):
        self.cfg = config or APIKeyManagerConfig()
        self._api_key_header = APIKeyHeader(name=self.cfg.header_name, auto_error=False)

        # 只快取純量資料
        self._api_cache: Dict[str, ApiKeyPublic] = {}

        # 快取使用次數與限制
        self._api_cache_usage_restrictions: int = 1000
        self._api_cache_usage_count: Dict[str, int] = {}

    # ---------- 基礎工具 ----------

    @staticmethod
    def hash_token(token: str) -> str:
        return sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def generate_token(nbytes: int = 48) -> str:
        return secrets.token_urlsafe(nbytes)

    # ---------- 內部：scopes 正規化/驗證 ----------

    def _normalize_scopes(self, scopes: Optional[Iterable[str]]) -> list[str]:
        if not scopes:
            return []
        uniq = []
        seen = set()
        for s in scopes:
            s = (s or "").strip()
            if not s:
                continue
            if s not in seen:
                uniq.append(s)
                seen.add(s)
        # 檢查是否在允許清單內（不想嚴格也可關掉這段）
        illegal = [s for s in uniq if s not in self.cfg.allowed_scopes]
        if illegal:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Illegal scopes: {illegal}; allowed = {sorted(self.cfg.allowed_scopes)}"
            )
        return uniq

    @staticmethod
    def _check_scopes(granted: Iterable[str], needed: Iterable[str], mode: Literal["all", "any"] = "all") -> bool:
        g = set(granted or [])
        n = [s for s in (needed or []) if s]
        if not n:
            return True
        return g.issuperset(n) if mode == "all" else (len(g.intersection(n)) > 0)

    # ---------- 建立 / 旋轉 / 啟停（管理面：仍使用 ORM；不進快取，不跨請求，所以安全） ----------

    async def create(
        self,
        db: AsyncSession,
        *,
        name: str,
        owner_id: int,
        scopes: Optional[Iterable[str]] = None,
        rate_limit_per_min: int | None = None,
        quota_per_day: int | None = None,
        active: bool = True,
    ) -> Tuple[api_keys.Table, str]:
        # 檢查 owner
        row = await db.execute(select(users.Table).where(users.Table.id == owner_id))
        if not row.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Owner user not found")

        token = self.generate_token()
        record = api_keys.Table(
            name=name,
            owner_id=owner_id,
            token_hash=self.hash_token(token),
            scopes=self._normalize_scopes(scopes),
            rate_limit_per_min=rate_limit_per_min,
            quota_per_day=quota_per_day,
            active=active,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record, token

    async def rotate(self, db: AsyncSession, *, key_id: UUID_t) -> Tuple[api_keys.Table, str]:
        row = await db.execute(select(api_keys.Table).where(api_keys.Table.id == key_id))
        rec = row.scalar_one_or_none()
        if not rec:
            raise HTTPException(status_code=404, detail="Key not found")
        token = self.generate_token()
        rec.token_hash = self.hash_token(token)
        db.add(rec)
        await db.commit()
        await db.refresh(rec)
        return rec, token

    async def set_active(self, db: AsyncSession, *, key_id: UUID_t, active: bool) -> api_keys.Table:
        row = await db.execute(select(api_keys.Table).where(api_keys.Table.id == key_id))
        rec = row.scalar_one_or_none()
        if not rec:
            raise HTTPException(status_code=404, detail="Key not found")
        rec.active = active
        db.add(rec)
        await db.commit()
        await db.refresh(rec)
        return rec

    async def set_scopes(self, db: AsyncSession, *, key_id: UUID_t, scopes: Iterable[str]) -> api_keys.Table:
        row = await db.execute(select(api_keys.Table).where(api_keys.Table.id == key_id))
        rec = row.scalar_one_or_none()
        if not rec:
            raise HTTPException(status_code=404, detail="Key not found")
        rec.scopes = self._normalize_scopes(scopes)
        db.add(rec)
        await db.commit()
        await db.refresh(rec)
        return rec

    async def get(self, db: AsyncSession, *, key_id: UUID_t) -> api_keys.Table:
        row = await db.execute(select(api_keys.Table).where(api_keys.Table.id == key_id))
        rec = row.scalar_one_or_none()
        if not rec:
            raise HTTPException(status_code=404, detail="Key not found")
        return rec

    async def list_all(self, db: AsyncSession, *, owner_id: int | None = None) -> list[api_keys.Table]:
        stmt = select(api_keys.Table).order_by(api_keys.Table.id.desc())
        if owner_id is not None:
            stmt = stmt.where(api_keys.Table.owner_id == owner_id)
        rows = await db.execute(stmt)
        return list(rows.scalars().all())

    # ---------- 查詢 / 驗證（服務面：只使用純量，以避免跨請求 ORM 問題） ----------

    async def verify_token(self, db: AsyncSession, *, raw_token: str) -> ApiKeyPublic:
        """
        1) 只 SELECT 需要的欄位（非 ORM instance）
        2) 以 SQL UPDATE 寫入 last_used_at（不載入 ORM，不會造成欄位過期或 instance detaching）
        3) 回傳 ApiKeyPublic（純量 dict），可安全放進快取
        """
        if not raw_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")

        h = self.hash_token(raw_token)

        # 只抓需要的欄位
        row = await db.execute(
            select(
                api_keys.Table.id,
                api_keys.Table.owner_id,
                api_keys.Table.scopes,
                api_keys.Table.active,
            ).where(api_keys.Table.token_hash == h)
        )
        rec = row.first()
        if rec is None or not rec.active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

        # 以 UPDATE 寫入 last_used_at，避免 ORM instance
        await db.execute(
            update(api_keys.Table)
            .where(api_keys.Table.id == rec.id)
            .values(last_used_at=datetime.now(timezone.utc))
        )
        await db.commit()

        # 回傳純量 dict
        return ApiKeyPublic(
            id=str(rec.id) if not isinstance(rec.id, int) else rec.id,
            owner_id=int(rec.owner_id),
            scopes=list(rec.scopes or []),
            active=bool(rec.active),
        )

    async def check_token_cached(self, db: AsyncSession, *, raw_token: str) -> ApiKeyPublic:
        """
        驗證 API Key，並使用快取減少資料庫查詢。
        只快取 ApiKeyPublic（純量 dict），不會有 ORM 跨請求 detaching 問題。
        """
        if raw_token in self._api_cache:
            self._api_cache_usage_count[raw_token] = self._api_cache_usage_count.get(raw_token, 0) + 1
            if self._api_cache_usage_count[raw_token] > self._api_cache_usage_restrictions:
                await self.refresh_cache(raw_token=raw_token)  # 超過使用次數限制，移除快取
                return await self.check_token_cached(db, raw_token=raw_token)  # 重新查詢
            return self._api_cache[raw_token]

        data = await self.verify_token(db, raw_token=raw_token)  # ApiKeyPublic
        self._api_cache[raw_token] = data
        return data

    async def refresh_cache(self, *, raw_token: str) -> None:
        """ 將指定的 raw_token 從快取中移除 """
        self._api_cache.pop(raw_token, None)
        self._api_cache_usage_count.pop(raw_token, None)

    # ---------- FastAPI 依賴：基本驗證 + 選擇性 scopes 驗證 ----------
    # 我把回傳型別與內部使用全部改用 ApiKeyPublic（純量 dict）

    def require(
        self,
        needed_scopes: Optional[Iterable[str]] = None,
        mode: Literal["all", "any"] = "all",
    ) -> Callable[..., Awaitable[ApiKeyPublic]]:
        """
        驗證 API Key，並檢查是否具備 needed_scopes。
        mode = 'all'：需要全部；'any'：任一即可。
        這裡我回傳 ApiKeyPublic（純量），並把資料放進 request.state。
        """
        needed_scopes = list(needed_scopes or [])

        async def _dep(
            request: Request,
            token: Optional[str] = Security(self._api_key_header),
            api_key_query: Optional[str] = Query(None, alias="api-key"),
            db: AsyncSession = Security(get_session),
        ) -> ApiKeyPublic:
            raw_token = token or api_key_query or ""
            rec = await self.check_token_cached(db, raw_token=raw_token)  # ApiKeyPublic
            if needed_scopes and not self._check_scopes(rec["scopes"], needed_scopes, mode=mode):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient scope")

            # 存入 request.state 的也是純量資料
            request.state.api_key = rec
            request.state.key_owner_id = rec["owner_id"]
            request.state.key_scopes = rec["scopes"] or []

            return rec

        return _dep

    def require_scopes(
        self,
        *needed_scopes: str,
        mode: Literal["all", "any"] = "all",
    ) -> Callable[..., Awaitable[ApiKeyPublic]]:
        """
        方便用法：@router.post(..., dependencies=[Depends(manager.require_scopes("uploader"))])
        仍回傳 ApiKeyPublic（純量）。
        """
        return self.require(needed_scopes=needed_scopes, mode=mode)
