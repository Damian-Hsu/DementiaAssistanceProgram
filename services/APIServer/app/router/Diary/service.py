from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from ...DataAccess.Connect import get_session
from ...DataAccess.tables import diary, diary_chunks
from sqlalchemy import select, insert, delete
from ...security.deps import get_current_user
from ...DataAccess.task_producer import enqueue
from datetime import date
from typing import List
import json

diary_router = APIRouter(prefix="/diary", tags=["diary"])

def chunk_text(text: str, max_chunk_size: int = 500) -> List[str]:
    """Simple text chunking by paragraphs and length."""
    # Split by paragraphs first
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    chunks = []
    
    for para in paragraphs:
        if len(para) <= max_chunk_size:
            chunks.append(para)
        else:
            # Split long paragraphs into smaller chunks
            words = para.split()
            current_chunk = ""
            for word in words:
                if len(current_chunk + " " + word) <= max_chunk_size:
                    current_chunk += " " + word if current_chunk else word
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = word
            if current_chunk:
                chunks.append(current_chunk)
    
    return chunks

@diary_router.post("/generate-embeddings/{date_str}")
async def generate_diary_embeddings(
    date_str: str,
    db: AsyncSession = Depends(get_session),
    current_user = Depends(get_current_user)
):
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    # Find the diary entry
    stmt = select(diary.Table).where(
        diary.Table.user_id == current_user.id,
        diary.Table.diary_date == target_date
    )
    res = await db.execute(stmt)
    diary_entry = res.scalar_one_or_none()
    
    if not diary_entry or not diary_entry.content:
        raise HTTPException(status_code=404, detail="Diary entry not found")

    # Check if already processed
    stmt_chunks = select(diary_chunks.Table).where(
        diary_chunks.Table.daily_summary_id == diary_entry.id
    )
    res_chunks = await db.execute(stmt_chunks)
    existing_chunks = res_chunks.scalars().all()
    
    if existing_chunks and all(c.embedding is not None for c in existing_chunks):
        raise HTTPException(status_code=400, detail="Embeddings already generated")

    # Chunk the text
    chunks = chunk_text(diary_entry.content)
    
    # Call Celery task for embedding generation
    try:
        task_result = enqueue("tasks.generate_diary_embeddings", {
            "diary_id": str(diary_entry.id),
            "chunks": chunks
        })
        
        # Wait for result (blocking for now, should use async in production)
        import asyncio
        from functools import partial
        
        def wait_for_task(task_res):
            return task_res.get(timeout=60)  # 60s timeout
            
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, partial(wait_for_task, task_result))
        
        return {"status": "success", "message": "Embeddings generated", "chunks_count": len(chunks)}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding generation failed: {str(e)}")

@diary_router.delete("/embeddings/{date_str}")
async def delete_diary_embeddings(
    date_str: str,
    db: AsyncSession = Depends(get_session),
    current_user = Depends(get_current_user)
):
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    # Find the diary entry
    stmt = select(diary.Table).where(
        diary.Table.user_id == current_user.id,
        diary.Table.diary_date == target_date
    )
    res = await db.execute(stmt)
    diary_entry = res.scalar_one_or_none()
    
    if not diary_entry:
        raise HTTPException(status_code=404, detail="Diary entry not found")

    # Delete chunks
    await db.execute(
        delete(diary_chunks.Table).where(
            diary_chunks.Table.daily_summary_id == diary_entry.id
        )
    )
    
    return {"status": "success", "message": "Embeddings deleted"}

