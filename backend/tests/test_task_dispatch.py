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


# ---------- format_error：异常信息不能为空 ----------
# 历史教训：网络类异常（httpx.ConnectError）的 str() 为空，
# 直接落库会让任务"失败但无任何原因"，用户无从排查。
# format_error 兜底为异常类名，保证错误信息始终可见。

def test_format_error_keeps_normal_message():
    from app.tasks._common import format_error
    assert format_error(ValueError("数据集不存在")) == "数据集不存在"


def test_format_error_falls_back_to_type_name_when_message_empty():
    """httpx.ConnectError 等网络异常的 str() 为空字符串"""
    import httpx
    from app.tasks._common import format_error
    exc = httpx.ConnectError("")  # 空消息
    assert str(exc) == ""  # 前置确认：原始 str 确实为空
    result = format_error(exc)
    assert result == "ConnectError", "空消息异常必须回退为类名，不能落库为空"
    assert result.strip(), "format_error 永不返回空串"


def test_format_error_never_returns_blank_for_empty_exception():
    """兜底也覆盖普通空消息异常"""
    from app.tasks._common import format_error
    assert format_error(Exception()).strip()
    assert format_error(Exception("   ")).strip()
