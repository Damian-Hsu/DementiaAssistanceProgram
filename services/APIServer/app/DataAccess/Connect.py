from fastapi import Depends
from typing import Annotated
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
import asyncio

from . import tables
import pkgutil
import importlib
load_dotenv()

# Database connection configuration
# 內部連接使用 Docker 服務名稱
DB_HOST = os.getenv('DB_HOST', 'postgres')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'dementia')
DB_USER = os.getenv('DB_SUPERUSER', 'postgres')
DB_PASSWORD = os.getenv('DB_SUPERPASS', 'default_password')

# Build database connection URL
DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# print(f"Connecting to database: {DB_HOST}:{DB_PORT}/{DB_NAME}")

# 建立 Engine（同步）

engine = create_async_engine(
    DATABASE_URL,
    echo=False, # 需要時改True可以觀察SQL
    pool_pre_ping=True,
)


# SessionFactory 與 FastAPI 依賴注入（同步）

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_session():
    async with AsyncSessionLocal() as session:
        yield session

SessionDep = Annotated[AsyncSession, Depends(get_session)]

def import_models():
    """
    確保所有 ORM models 都會被 import，metadata 才能註冊成功
    """
    package = tables
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        if module_name.startswith("_"):
            continue
        importlib.import_module(f"{package.__name__}.{module_name}")


async def create_db_and_tables() -> None:
    import_models()
    async with engine.begin() as conn:
        await conn.run_sync(tables.ORMBase.metadata.create_all)
        await conn.execute(text(
            "ALTER TABLE IF EXISTS vlogs "
            "ADD COLUMN IF NOT EXISTS progress DOUBLE PRECISION DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE IF EXISTS vlogs "
            "ADD COLUMN IF NOT EXISTS status_message TEXT"
        ))
        await conn.execute(text(
            "ALTER TABLE IF EXISTS recordings "
            "ADD COLUMN IF NOT EXISTS thumbnail_s3_key TEXT"
        ))
        await conn.execute(text(
            "ALTER TABLE IF EXISTS vlogs "
            "ADD COLUMN IF NOT EXISTS thumbnail_s3_key TEXT"
        ))
        await conn.execute(text(
            "ALTER TABLE IF EXISTS music "
            "ADD COLUMN IF NOT EXISTS content_type VARCHAR(100)"
        ))
        # LLM 使用量紀錄：新增 provider / model_name 欄位（向後相容）
        await conn.execute(text(
            "ALTER TABLE IF EXISTS llm_usage_logs "
            "ADD COLUMN IF NOT EXISTS provider VARCHAR(32)"
        ))
        await conn.execute(text(
            "ALTER TABLE IF EXISTS llm_usage_logs "
            "ADD COLUMN IF NOT EXISTS model_name VARCHAR(128)"
        ))
        # 移除 users.dementia_level（此欄位已不再使用）
        await conn.execute(text(
            "ALTER TABLE IF EXISTS users "
            "DROP COLUMN IF EXISTS dementia_level"
        ))
        # --- 移除 daily_summaries，統一以 diary 作為日記摘要主表 ---
        # diary_chunks：將 daily_summary_id -> diary_id（直接指向 diary.id）
        await conn.execute(text(
            "ALTER TABLE IF EXISTS diary_chunks "
            "ADD COLUMN IF NOT EXISTS diary_id UUID"
        ))
        # 既有資料搬移：若 diary_id 尚未填，使用舊 daily_summary_id 值（過去實作實際塞的是 diary.id）
        await conn.execute(text(
            "UPDATE diary_chunks "
            "SET diary_id = daily_summary_id "
            "WHERE diary_id IS NULL AND daily_summary_id IS NOT NULL"
        ))
        # 移除舊 FK/欄位（若存在）
        await conn.execute(text(
            "ALTER TABLE IF EXISTS diary_chunks "
            "DROP CONSTRAINT IF EXISTS diary_chunks_daily_summary_id_fkey"
        ))
        await conn.execute(text(
            "ALTER TABLE IF EXISTS diary_chunks "
            "DROP COLUMN IF EXISTS daily_summary_id"
        ))
        # 新增 diary_id 外鍵（PostgreSQL 不支援 ADD CONSTRAINT IF NOT EXISTS，改用 pg_constraint 檢查）
        await conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'diary_chunks_diary_id_fkey'
                ) THEN
                    ALTER TABLE diary_chunks
                    ADD CONSTRAINT diary_chunks_diary_id_fkey
                    FOREIGN KEY (diary_id) REFERENCES diary(id) ON DELETE CASCADE;
                END IF;
            END $$;
        """))
        # 若資料已完整搬移，將 diary_id 設為 NOT NULL（避免舊資料尚未搬移時啟動失敗）
        await conn.execute(text("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='diary_chunks' AND column_name='diary_id'
                ) AND NOT EXISTS (
                    SELECT 1 FROM diary_chunks WHERE diary_id IS NULL
                ) THEN
                    ALTER TABLE diary_chunks ALTER COLUMN diary_id SET NOT NULL;
                END IF;
            END $$;
        """))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_diary_chunks_diary_id ON diary_chunks(diary_id)"
        ))
        # 刪除冗餘表：daily_summaries
        await conn.execute(text(
            "DROP TABLE IF EXISTS daily_summaries CASCADE"
        ))
        # 確保 settings 和 api_key_blacklist 表格存在（如果不存在會自動創建）
        # 這些表格通過 ORM 自動創建，這裡只是確保遷移完成
async def recreate_all():
    import_models()
    async with engine.begin() as conn:
        await conn.run_sync(tables.ORMBase.metadata.drop_all)
        await conn.run_sync(tables.ORMBase.metadata.create_all)

async def test_connection() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(recreate_all())
    print("已註冊的表：", tables.ORMBase.metadata.tables.keys())