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
        from ..models import document, dataset, evaluation, model, rag_system, metric, sync, hot_news

        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)

        # 添加新列（如果不存在）
        from sqlalchemy import text

        # metric_definitions.eval_stage
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'metric_definitions' AND column_name = 'eval_stage'
        """))
        if result.fetchone() is None:
            await conn.execute(text("""
                ALTER TABLE metric_definitions
                ADD COLUMN eval_stage VARCHAR(20) NOT NULL DEFAULT 'result'
            """))

        # evaluations.invocation_batch_id
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'evaluations' AND column_name = 'invocation_batch_id'
        """))
        if result.fetchone() is None:
            await conn.execute(text("""
                ALTER TABLE evaluations
                ADD COLUMN invocation_batch_id UUID
            """))

        # evaluations.reuse_invocation
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'evaluations' AND column_name = 'reuse_invocation'
        """))
        if result.fetchone() is None:
            await conn.execute(text("""
                ALTER TABLE evaluations
                ADD COLUMN reuse_invocation BOOLEAN DEFAULT true
            """))

        # invocation_results.retrieval_ids
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'invocation_results' AND column_name = 'retrieval_ids'
        """))
        if result.fetchone() is None:
            await conn.execute(text("""
                ALTER TABLE invocation_results
                ADD COLUMN retrieval_ids JSONB
            """))

        # eval_results.invocation_result_id
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'eval_results' AND column_name = 'invocation_result_id'
        """))
        if result.fetchone() is None:
            await conn.execute(text("""
                ALTER TABLE eval_results
                ADD COLUMN invocation_result_id UUID
            """))


async def close_db():
    """关闭数据库连接"""
    await async_engine.dispose()


# Celery 任务专用异步引擎（独立于 FastAPI 应用）
# 注意：在 prefork 模式下，需要在每个 worker 进程中重新创建引擎
# 所以这里初始化为 None，在 worker 进程初始化时创建
celery_async_engine = None
CeleryAsyncSessionLocal = None


def _create_celery_engine():
    """在 Celery worker 进程中创建数据库引擎"""
    global celery_async_engine, CeleryAsyncSessionLocal
    if celery_async_engine is None:
        celery_async_engine = create_async_engine(
            settings.DATABASE_URL,
            echo=settings.APP_DEBUG,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10
        )
        CeleryAsyncSessionLocal = async_sessionmaker(
            bind=celery_async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False
        )
    return celery_async_engine


def dispose_celery_engine():
    """清理 Celery 数据库引擎（在 worker 进程退出时调用）"""
    global celery_async_engine, CeleryAsyncSessionLocal
    if celery_async_engine is not None:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(celery_async_engine.dispose())
            else:
                loop.run_until_complete(celery_async_engine.dispose())
        except Exception:
            pass
        celery_async_engine = None
        CeleryAsyncSessionLocal = None


from contextlib import asynccontextmanager


@asynccontextmanager
async def get_db_context():
    """异步数据库上下文管理器（用于 Celery 任务等场景）

    Celery 任务使用独立的数据库引擎，避免 event loop 冲突。

    用法:
        async with get_db_context() as db:
            # 使用 db 进行数据库操作
            await db.commit()
    """
    # 确保引擎已创建
    _create_celery_engine()

    async with CeleryAsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()