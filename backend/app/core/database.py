# 数据库连接
import logging

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

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


async def init_db():
    """初始化数据库（创建所有表）"""
    async with async_engine.begin() as conn:
        # 导入所有模型（确保每个模型模块都注册到 Base.metadata）
        from ..models import (
            document, dataset, evaluation, invocation, annotation_correction,
            model, model_log, model_mapping, rag_system, metric, sync,
            hot_news, load_test, prompt, vibe_agent, doc_parse,
            training_data_eval, open_source_dataset,
        )

        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)

        # 添加新列（如果不存在）
        from sqlalchemy import text

        # models.save_logs
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'models' AND column_name = 'save_logs'
        """))
        if result.fetchone() is None:
            await conn.execute(text("""
                ALTER TABLE models
                ADD COLUMN save_logs BOOLEAN DEFAULT false
            """))

        # models.is_vlm
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'models' AND column_name = 'is_vlm'
        """))
        if result.fetchone() is None:
            await conn.execute(text("""
                ALTER TABLE models
                ADD COLUMN is_vlm BOOLEAN DEFAULT false
            """))

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

        # evaluations.cancel_requested（协作式取消标志）
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'evaluations' AND column_name = 'cancel_requested'
        """))
        if result.fetchone() is None:
            await conn.execute(text("""
                ALTER TABLE evaluations
                ADD COLUMN cancel_requested BOOLEAN NOT NULL DEFAULT false
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

        # model_request_logs.source
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'model_request_logs' AND column_name = 'source'
        """))
        if result.fetchone() is None:
            await conn.execute(text("""
                ALTER TABLE model_request_logs
                ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'direct'
            """))

        # model_request_logs.mapping_id
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'model_request_logs' AND column_name = 'mapping_id'
        """))
        if result.fetchone() is None:
            await conn.execute(text("""
                ALTER TABLE model_request_logs
                ADD COLUMN mapping_id UUID
            """))
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_model_request_logs_mapping_id
                ON model_request_logs (mapping_id)
            """))

        # load_tests.target_model_id（大模型直连压测）
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'load_tests' AND column_name = 'target_model_id'
        """))
        if result.fetchone() is None:
            await conn.execute(text("""
                ALTER TABLE load_tests
                ADD COLUMN target_model_id UUID
            """))
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_load_tests_target_model_id
                ON load_tests (target_model_id)
            """))
            # 旧数据 rag_system_id 为 NOT NULL，放宽为可空以兼容两种压测对象
            await conn.execute(text("""
                ALTER TABLE load_tests
                ALTER COLUMN rag_system_id DROP NOT NULL
            """))

        # documents.dataset_id（文档归属数据集，数据集内触发解析时填写）
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'documents' AND column_name = 'dataset_id'
        """))
        if result.fetchone() is None:
            await conn.execute(text("""
                ALTER TABLE documents
                ADD COLUMN dataset_id UUID
            """))
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_documents_dataset_id
                ON documents (dataset_id)
            """))

        # doc_parse_batches.dataset_id（解析批次归属数据集）
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'doc_parse_batches' AND column_name = 'dataset_id'
        """))
        if result.fetchone() is None:
            await conn.execute(text("""
                ALTER TABLE doc_parse_batches
                ADD COLUMN dataset_id UUID
            """))
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_doc_parse_batches_dataset_id
                ON doc_parse_batches (dataset_id)
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
    """在 Celery worker 进程中创建数据库引擎

    注意：Celery 任务通过 run_async() 每次使用全新的 event loop，
    asyncpg 连接绑定创建时的 event loop，跨 loop 复用池中连接会报
    'NoneType' object has no attribute 'send'。因此这里必须关闭连接池
    （poolclass=NullPool），每次借出连接都是新建，用完即真正关闭。
    """
    global celery_async_engine, CeleryAsyncSessionLocal
    if celery_async_engine is None:
        from sqlalchemy.pool import NullPool
        celery_async_engine = create_async_engine(
            settings.DATABASE_URL,
            echo=settings.APP_DEBUG,
            pool_pre_ping=True,
            poolclass=NullPool,
            # NullPool 每次借出新建连接；评估任务单条可达 10min+（思考型模型
            # 多轮 LLM 调用），若连接在任务中途被服务端/防火墙掐断，
            # 收尾落库全部失败、状态卡 running。tcp 保活 + 语句超时兜底：
            # keepalives 让空闲连接可被尽早检出，statement 超时避免无界等待。
            connect_args={
                "timeout": 10,  # 建连超时（秒）
                "command_timeout": None,  # 语句执行不额外限时（长事务由任务层控制）
                "server_settings": {
                    "application_name": "jq_eval_celery",
                },
            },
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
        except Exception as e:
            # 引擎清理失败不应阻塞 worker 退出，但要留痕
            logging.getLogger(__name__).warning(f"Celery 数据库引擎清理失败: {e}")
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