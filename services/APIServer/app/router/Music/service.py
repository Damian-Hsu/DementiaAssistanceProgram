from __future__ import annotations

import json
import uuid
from io import BytesIO
from datetime import datetime, timezone
from typing import List

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Path,
    UploadFile,
    File,
    Form,
    Request,
)
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ...DataAccess.Connect import get_session
from ...DataAccess.tables import music as music_table, users
from ...security.deps import get_current_user
from ...utils import (
    generate_presigned_url,
    normalize_s3_key,
    upload_fileobj,
    delete_object,
)
from ..Admin.service import ensure_admin  # re-use admin guard
from .DTO import MusicRead, MusicListResponse, MusicUrlResponse, MusicAdminRead


music_router = APIRouter(prefix="/music", tags=["music"])
admin_music_router = APIRouter(prefix="/admin/music", tags=["admin"])


def _build_music_read(
    record: music_table.Table,
    uploader_name: str | None,
    include_s3: bool = False,
) -> MusicRead | MusicAdminRead:
    base_kwargs = {
        "id": str(record.id),
        "name": record.name,
        "composer": record.composer,
        "description": record.description,
        "duration": record.duration,
        "metadata": record.meta_data,
        "uploader_user_id": record.uploader_user_id,
        "uploader_name": uploader_name,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "content_type": record.content_type,
    }
    if include_s3:
        return MusicAdminRead(**base_kwargs, s3_key=record.s3_key)
    return MusicRead(**base_kwargs)


async def _get_music_or_404(
    music_id: uuid.UUID,
    db: AsyncSession,
) -> music_table.Table:
    stmt = select(music_table.Table).where(music_table.Table.id == music_id)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="音樂資料不存在")
    return record


@music_router.get("", response_model=MusicListResponse)
async def list_music(
    skip: int = Query(0, ge=0, description="跳過筆數"),
    limit: int = Query(50, ge=1, le=200, description="返回筆數"),
    db: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    """列出可用的音樂清單"""
    base_query = (
        select(
            music_table.Table,
            users.Table.name.label("uploader_name"),
        )
        .join(users.Table, music_table.Table.uploader_user_id == users.Table.id, isouter=True)
        .order_by(desc(music_table.Table.created_at))
        .offset(skip)
        .limit(limit)
    )

    result = await db.execute(base_query)
    rows = result.all()

    total_result = await db.execute(select(func.count()).select_from(music_table.Table))
    total = total_result.scalar() or 0

    items: List[MusicRead] = []
    for record, uploader_name in rows:
        items.append(_build_music_read(record, uploader_name))

    return MusicListResponse(items=items, total=total)


@music_router.get("/{music_id}", response_model=MusicRead)
async def get_music(
    music_id: uuid.UUID = Path(..., description="音樂 ID"),
    db: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    """取得單首音樂的詳細資料"""
    record = await _get_music_or_404(music_id, db)
    uploader_name = None
    if record.uploader_user_id:
        res = await db.execute(
            select(users.Table.name).where(users.Table.id == record.uploader_user_id)
        )
        uploader_name = res.scalar_one_or_none()
    return _build_music_read(record, uploader_name)


@music_router.get("/{music_id}/url", response_model=MusicUrlResponse)
async def get_music_url(
    music_id: uuid.UUID = Path(..., description="音樂 ID"),
    ttl: int = Query(3600, ge=60, le=86400, description="URL 有效時間(秒)"),
    db: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    """取得音樂播放 URL (MinIO 預簽名 URL)"""
    record = await _get_music_or_404(music_id, db)
    normalized_key = normalize_s3_key(record.s3_key)
    filename = normalized_key.rsplit("/", 1)[-1]
    disposition = f'inline; filename="{filename}"'
    url = generate_presigned_url(
        normalized_key,
        ttl,
        content_type=record.content_type or "audio/mpeg",
        content_disposition=disposition,
    )
    expires_at = int(datetime.now(timezone.utc).timestamp()) + ttl
    return MusicUrlResponse(url=url, ttl=ttl, expires_at=expires_at)


@admin_music_router.get("", response_model=MusicListResponse)
async def list_music_admin(
    skip: int = Query(0, ge=0, description="跳過筆數"),
    limit: int = Query(50, ge=1, le=200, description="返回筆數"),
    db: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    """[Admin] 列出音樂清單"""
    ensure_admin(current_user)
    return await list_music(skip=skip, limit=limit, db=db, current_user=current_user)


@admin_music_router.post("", response_model=MusicAdminRead, status_code=201)
async def upload_music(
    request: Request,
    file: UploadFile = File(..., description="音樂檔案"),
    name: str = Form(..., description="音樂名稱"),
    composer: str | None = Form(None, description="製作者"),
    description: str | None = Form(None, description="詳細資訊"),
    metadata: str | None = Form(None, description="附加 metadata (JSON 字串，可選)"),
    db: AsyncSession = Depends(get_session),
):
    current_user = request.state.current_user
    ensure_admin(current_user)

    if file.content_type is None or not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="僅支援上傳音訊檔案")

    raw_data = await file.read()
    if not raw_data:
        raise HTTPException(status_code=400, detail="檔案內容為空")

    file_ext = ""
    if file.filename and "." in file.filename:
        file_ext = file.filename.rsplit(".", 1)[-1].lower()
    music_uuid = uuid.uuid4().hex
    object_name = f"{current_user.id}/music/{music_uuid}"
    if file_ext:
        object_name = f"{object_name}.{file_ext}"

    upload_fileobj(
        BytesIO(raw_data),
        len(raw_data),
        object_name,
        content_type=file.content_type,
    )

    parsed_metadata = {
        "original_filename": file.filename,
        "content_length": len(raw_data),
    }
    if metadata:
        try:
            user_meta = json.loads(metadata)
            if isinstance(user_meta, dict):
                parsed_metadata.update(user_meta)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="metadata 必須為合法的 JSON 字串")

    record = music_table.Table(
        name=name,
        composer=composer,
        description=description,
        uploader_user_id=current_user.id,
        meta_data=parsed_metadata,
        duration=None,
        s3_key=object_name,
        content_type=file.content_type,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    uploader_name = getattr(current_user, "name", None)
    return _build_music_read(record, uploader_name, include_s3=True)


@admin_music_router.delete("/{music_id}")
async def delete_music(
    music_id: uuid.UUID = Path(..., description="音樂 ID"),
    db: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    """[Admin] 刪除音樂"""
    ensure_admin(current_user)
    record = await _get_music_or_404(music_id, db)

    try:
        delete_object(record.s3_key)
    except Exception as exc:
        # 刪除失敗不影響資料庫刪除，但紀錄下來
        print(f"[Music] 刪除 S3 物件失敗 ({record.s3_key}): {exc}")

    await db.delete(record)
    await db.commit()
    return {"ok": True}

