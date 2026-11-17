# 多模态评测任务回归测试
#
# 覆盖两个曾经让真实运行失败的问题：
#   1. rollback 后继续访问 ORM 样本/模型 -> DetachedInstanceError
#   2. commit_with_retry 要求 apply 可 await，而写明细的 apply 是同步函数
import contextlib
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import MMDataset, MMEvalQueryResult, MMEvalRun, MMSample, Model
from app.tasks import mm_embedding_tasks


class _FakeTask:
    def update_state(self, **_kwargs):
        return None


class _FakeClient:
    """按文本查表返回确定性向量，正例必须排第一"""

    image_transport = "data_url"

    _VECTORS = {
        "q1": [1.0, 0.0],
        "a": [1.0, 0.0],
        "b": [0.0, 1.0],
        "q2": [0.0, 1.0],
        "c": [0.0, 1.0],
        "d": [1.0, 0.0],
    }

    def __init__(self, model, params=None):
        self.model = model
        self.params = params or {}

    async def embed(self, items, progress_cb=None, cancel_cb=None):
        vectors = [self._VECTORS[item.text] for item in items]
        if progress_cb:
            await progress_cb(len(vectors), len(vectors))
        return vectors


@pytest.mark.asyncio
async def test_task_completes_after_session_detach(db_session: AsyncSession, monkeypatch):
    dataset = MMDataset(name="task-test", status="ready", record_count=4, query_count=2)
    model = Model(
        name="fake-mm",
        model_type="embedding",
        provider="openai",
        model_name="fake-mm",
        endpoint="http://example.invalid/v1",
        params={},
        status="active",
    )
    db_session.add_all([dataset, model])
    await db_session.commit()

    rows = [
        ("q1", "a", 1),
        ("q1", "b", 0),
        ("q2", "c", 1),
        ("q2", "d", 0),
    ]
    db_session.add_all(
        [
            MMSample(
                dataset_id=dataset.id,
                seq=index,
                subset="T",
                qid=qid,
                query_text=qid,
                target_text=target,
                label=label,
            )
            for index, (qid, target, label) in enumerate(rows)
        ]
    )
    run = MMEvalRun(
        id=uuid4(),
        name="task-run",
        dataset_id=dataset.id,
        model_id=model.id,
        status="running",
        params={"request_format": "text_only", "top_k": 10},
    )
    db_session.add(run)
    await db_session.commit()
    run_id = run.id

    factory = async_sessionmaker(
        db_session.bind, class_=AsyncSession, expire_on_commit=False
    )

    @contextlib.asynccontextmanager
    async def fake_db_context():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    monkeypatch.setattr(mm_embedding_tasks, "get_db_context", fake_db_context)
    monkeypatch.setattr(mm_embedding_tasks, "MMEmbeddingClient", _FakeClient)

    result = await mm_embedding_tasks._run_mm_embedding_eval(_FakeTask(), run_id)

    assert result["status"] == "completed", result
    # 任务用独立 session 落库，本 session 的 identity map 里还是旧状态
    db_session.expire_all()
    stored = await db_session.get(MMEvalRun, run_id)
    assert stored.status == "completed"
    assert stored.query_count == 2
    assert stored.metrics["recall@1"] == 1.0

    details = (
        await db_session.execute(
            select(MMEvalQueryResult).where(MMEvalQueryResult.run_id == run_id)
        )
    ).scalars().all()
    assert {row.qid for row in details} == {"q1", "q2"}
    assert all(row.rank == 1 for row in details)
