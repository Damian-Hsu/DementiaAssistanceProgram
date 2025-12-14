from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession


def extract_usage_from_response(resp: Any) -> Dict[str, int]:
    """從 Gemini / LLM 回應物件萃取 token 使用量（盡量相容不同 SDK 版本）。"""

    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if resp is None:
        return usage

    meta = getattr(resp, "usage_metadata", None)
    if meta is None and isinstance(resp, dict):
        meta = resp.get("usage_metadata")

    # google.generativeai: usage_metadata.prompt_token_count / candidates_token_count / total_token_count
    # 也可能是 dict 型態
    def _get(obj: Any, key: str) -> Optional[int]:
        if obj is None:
            return None
        if isinstance(obj, dict):
            v = obj.get(key)
        else:
            v = getattr(obj, key, None)
        try:
            return int(v) if v is not None else None
        except Exception:
            return None

    prompt = _get(meta, "prompt_token_count") or _get(meta, "prompt_tokens") or 0
    completion = _get(meta, "candidates_token_count") or _get(meta, "completion_tokens") or 0
    total = _get(meta, "total_token_count") or _get(meta, "total_tokens") or 0

    # 若 total 缺失，嘗試用 prompt+completion 推算
    if not total and (prompt or completion):
        total = prompt + completion

    usage["prompt_tokens"] = max(0, int(prompt))
    usage["completion_tokens"] = max(0, int(completion))
    usage["total_tokens"] = max(0, int(total))
    return usage


async def log_llm_usage(
    db: AsyncSession,
    *,
    user_id: int,
    source: str,
    provider: str | None = None,
    model_name: str | None = None,
    usage: Dict[str, int] | None = None,
    assistant_replies: int = 0,
    trace_id: str | None = None,
    meta: dict | None = None,
) -> None:
    """寫入一筆 LLM 使用量紀錄（best-effort，不應影響主要流程）。"""

    from ..DataAccess.tables import llm_usage_logs

    u = usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    row = llm_usage_logs.Table(
        user_id=user_id,
        source=source,
        provider=provider,
        model_name=model_name,
        prompt_tokens=int(u.get("prompt_tokens") or 0),
        completion_tokens=int(u.get("completion_tokens") or 0),
        total_tokens=int(u.get("total_tokens") or 0),
        assistant_replies=int(assistant_replies or 0),
        trace_id=trace_id,
        meta=meta,
    )

    try:
        # 若外層已有 transaction，避免再 begin；直接 add/flush 即可
        db.add(row)
        await db.flush()
    except Exception:
        # 嘗試用 transaction 方式再寫一次（避免部分情況 flush 失敗）
        try:
            async with db.begin():
                db.add(row)
        except Exception as e:
            print(f"[LLM Usage] log failed: user_id={user_id}, source={source}, err={e}")


