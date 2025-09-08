# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import secrets
from typing import Optional, Callable, Awaitable, Tuple, Iterable, Literal, Dict
from uuid import UUID as UUID_t

from fastapi import Security, HTTPException, status, Request, Depends, Query
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..DataAccess.Connect import get_session
from ..DataAccess.tables import api_keys, users


@dataclass(slots=True)
class APIKeyManagerConfig:
    header_name: str = "X-API-Key"
    show_token_once: bool = True
    # 允許的 scopes（先用固定集合，夠你大專專題）
    allowed_scopes: set[str] = field(default_factory=lambda: {
        "uploader",   # 允許呼叫 /jobs 建任務
        "compute",    # 允許呼叫 /jobs/{id}/complete 回報
        "mediamtx",   # 允許呼叫 /m2m/streams/auth
        "streaming",  # 允許呼叫 /m2m/streams/*（若有）
        "admin"       # 內部維運
    })


class APIKeyManager:
    """
    管理 API Key：產生、雜湊、建立、驗證、旋轉、啟停、查詢 + scopes。
    """

    def __init__(self, config: Optional[APIKeyManagerConfig] = None):
        self.cfg = config or APIKeyManagerConfig()
        self._api_key_header = APIKeyHeader(name=self.cfg.header_name, auto_error=False)
        self._api_cache:Dict[str,api_keys.Table] = {}
        self._api_cache_usage_restrictions: int = 1000  # 快取可以使用的次數
        self._api_cache_usage_count: Dict[str,int] = {}

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
    def _check_scopes(granted: Iterable[str], needed: Iterable[str], mode: Literal["all","any"]="all") -> bool:
        g = set(granted or [])
        n = [s for s in (needed or []) if s]
        if not n:
            return True
        return g.issuperset(n) if mode == "all" else (len(g.intersection(n)) > 0)

    # ---------- 建立 / 旋轉 / 啟停 ----------

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

    # （可選）更新 scopes
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

    # ---------- 查詢 / 驗證 ----------

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

    async def verify_token(self, db: AsyncSession, *, raw_token: str) -> api_keys.Table:
        if not raw_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")
        h = self.hash_token(raw_token)
        row = await db.execute(select(api_keys.Table).where(api_keys.Table.token_hash == h))
        rec = row.scalar_one_or_none()
        if rec is None or not rec.active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        rec.last_used_at = datetime.now(timezone.utc)
        db.add(rec)
        await db.commit()
        return rec
    
    async def check_token_cached(self, db: AsyncSession, *, raw_token: str) -> api_keys.Table:
        """ 驗證 API Key，並使用快取減少資料庫查詢 """

        if raw_token in self._api_cache:
            self._api_cache_usage_count[raw_token] += 1
            if self._api_cache_usage_count[raw_token] > self._api_cache_usage_restrictions:
                    await self.refresh_cache(raw_token=raw_token) # 超過使用次數限制，移除快取
                    return await self.check_token_cached(db, raw_token=raw_token) # 重新查詢
            return self._api_cache[raw_token]
        rec = await self.verify_token(db, raw_token=raw_token)
        self._api_cache[raw_token] = rec
        return rec
    
    async def refresh_cache(self, *, raw_token: str) -> None:
        """ 將指定的 raw_token 從快取中移除"""
        if raw_token in self._api_cache:
            del self._api_cache[raw_token]
            del self._api_cache_usage_count[raw_token]
    # ---------- FastAPI 依賴：基本驗證 + 選擇性 scopes 驗證 ----------

    def require(
        self,
        needed_scopes: Optional[Iterable[str]] = None,
        mode: Literal["all","any"] = "all",
    ) -> Callable[..., Awaitable[api_keys.Table]]:
        """
        最通用：驗證 API Key，並（可選）檢查是否具備 needed_scopes。
        mode = 'all'：需要全部；'any'：任一即可。
        """
        needed_scopes = list(needed_scopes or [])
        async def _dep(
            request: Request,
            token: Optional[str] = Security(self._api_key_header),
            api_key_query: Optional[str] = Query(None, alias="api-key"),
            db: AsyncSession = Security(get_session),
        ) -> api_keys.Table:
            raw_token = token or api_key_query or ""
            rec = await self.check_token_cached(db, raw_token=raw_token)
            if needed_scopes and not self._check_scopes(rec.scopes, needed_scopes, mode=mode):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient scope")
            request.state.api_key = rec
            request.state.key_owner_id = rec.owner_id
            request.state.key_scopes = rec.scopes or []
            return rec
        return _dep

    def require_scopes(
        self,
        *needed_scopes: str,
        mode: Literal["all","any"] = "all",
    ) -> Callable[..., Awaitable[api_keys.Table]]:
        """
        方便用法：@router.post(..., dependencies=[Depends(manager.require_scopes("uploader"))])
        """
        return self.require(needed_scopes=needed_scopes, mode=mode)
