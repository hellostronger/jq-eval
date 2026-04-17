# 数据库连接
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings

# 异步引擎
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

# 异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# 同步引擎（用于迁移等）
sync_engine = create_engine(
    settings.DATABASE_URL_SYNC,
    echo=settings.APP_DEBUG,
    pool_pre_ping=True
)

# 同步会话工厂
SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False
)

# 模型基类
Base = declarative_base()


# 异步数据库依赖
async def get_db() -> AsyncSession:
    """获取异步数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# 同步数据库依赖
def get_db_sync():
    """获取同步数据库会话"""
    db = SyncSessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def init_db():
    """初始化数据库（创建所有表）"""
    async with async_engine.begin() as conn:
        # 导入所有模型
        from ..models import document, dataset, evaluation, model, rag_system, metric, sync

        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """关闭数据库连接"""
    await async_engine.dispose()


from contextlib import asynccontextmanager


@asynccontextmanager
async def get_db_context():
    """异步数据库上下文管理器（用于 Celery 任务等场景）

    用法:
        async with get_db_context() as db:
            # 使用 db 进行数据库操作
            await db.commit()
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()