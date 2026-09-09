# 任务派发封装的回归测试
#
# 覆盖两类曾经的线上 bug：
# 1. "先 commit running → 再 delay"：broker 不可达时 delay 抛异常，
#    状态已提交为 running 且无人再改 → 任务永久卡 running。
# 2. retry 端点"先置 pending → delay → 再置 running"：秒级完成的 worker
#    写入 completed 会被随后的 running 覆盖 → 状态永久卡 running。
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1._common import start_task
from app.models import Model


@pytest.mark.asyncio
async def test_start_task_success_sets_running(db_session: AsyncSession, sample_llm_model: Model):
    """派发成功：状态先落库为 running，返回 dispatch 结果"""
    obj = sample_llm_model
    original = obj.status
    marker = object()

    result = await start_task(db_session, obj, lambda: marker)

    assert result is marker
    await db_session.refresh(obj)
    assert obj.status == "running"

    # 还原，避免影响其他 fixture 复用
    obj.status = original
    await db_session.commit()


@pytest.mark.asyncio
async def test_start_task_dispatch_failure_rolls_back_status(db_session: AsyncSession, sample_llm_model: Model):
    """派发失败：状态回滚为进入前的原值，抛 503，绝不残留 running"""
    from fastapi import HTTPException

    obj = sample_llm_model
    obj.status = "pending"
    await db_session.commit()

    def boom():
        raise ConnectionError("broker unreachable")

    with pytest.raises(HTTPException) as exc:
        await start_task(db_session, obj, boom)

    assert exc.value.status_code == 503
    await db_session.refresh(obj)
    assert obj.status == "pending", "派发失败后状态必须回滚，不能停留在 running"


@pytest.mark.asyncio
async def test_start_task_custom_fallback(db_session: AsyncSession, sample_llm_model: Model):
    """显式 fallback_value：失败后落到指定状态（retry 端点用 pending）"""
    from fastapi import HTTPException

    obj = sample_llm_model
    obj.status = "failed"
    await db_session.commit()

    def boom():
        raise ConnectionError("broker unreachable")

    with pytest.raises(HTTPException):
        await start_task(db_session, obj, boom, fallback_value="pending")

    await db_session.refresh(obj)
    assert obj.status == "pending"
