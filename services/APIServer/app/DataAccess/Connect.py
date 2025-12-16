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