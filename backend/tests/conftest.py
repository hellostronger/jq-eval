# pytest 配置和 fixtures
import pytest
import asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import get_db, Base
from app.models import Model, Dataset, QARecord, RAGSystem
from app.models.evaluation import Evaluation

# 测试数据库 URL（使用 SQLite 内存数据库）
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_engine():
    """创建测试数据库引擎"""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """创建测试数据库会话"""
    async_session = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """创建测试客户端"""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def sample_llm_model(db_session: AsyncSession) -> Model:
    """创建示例 LLM 模型"""
    model = Model(
        name="Test LLM",
        model_type="llm",
        provider="openai",
        model_name="gpt-4",
        endpoint="https://api.openai.com",
        api_key="test-key",
        params={"temperature": 0.7, "max_tokens": 1000},
        is_default=True,
        status="active"
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    return model


@pytest.fixture
async def sample_embedding_model(db_session: AsyncSession) -> Model:
    """创建示例 Embedding 模型"""
    model = Model(
        name="Test Embedding",
        model_type="embedding",
        provider="openai",
        model_name="text-embedding-ada-002",
        endpoint="https://api.openai.com",
        api_key="test-key",
        dimension=1536,
        max_input_length=8191,
        is_default=True,
        status="active"
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    return model


@pytest.fixture
async def sample_dataset(db_session: AsyncSession) -> Dataset:
    """创建示例数据集"""
    dataset = Dataset(
        name="Test Dataset",
        description="A test dataset for evaluation",
        status="active"
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def sample_rag_system(db_session: AsyncSession) -> RAGSystem:
    """创建示例 RAG 系统"""
    rag = RAGSystem(
        name="Test RAG System",
        system_type="custom",
        description="A test RAG system",
        connection_config={"api_url": "http://localhost:8000"},
        status="active"
    )
    db_session.add(rag)
    await db_session.commit()
    await db_session.refresh(rag)
    return rag