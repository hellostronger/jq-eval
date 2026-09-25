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


def test_format_error_is_reexported_from_core_for_all_layers():
    """tasks._common 只是重导出，各层（services/api）都从 core 取同一个实现"""
    from app.core.exceptions import format_error as core_fe
    from app.tasks._common import format_error as task_fe
    assert task_fe is core_fe


def test_format_error_equivalent_to_str_when_message_present():
    """机械替换的安全前提：消息非空时与 str(e) 完全等价

    全量把 str(e) 换成 format_error(e) 就是靠这条性质——
    只会把空串变成异常类名，不会改变任何已有的正常错误文案。
    """
    from app.tasks._common import format_error
    for msg in ["数据集不存在", "timeout after 300s", "500 Internal Server Error"]:
        exc = ValueError(msg)
        assert format_error(exc) == str(exc) == msg


def test_no_raw_str_exception_in_source():
    """源码里不应再有把异常 str() 化后落库/展示的裸写法

    空 str() 的网络异常（httpx.ConnectError 等）会让"失败"没有原因，
    这正是 format_error 要消灭的。ast 层面检查，避免正则误伤 str(uuid)。
    """
    import ast
    import pathlib

    app_dir = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in app_dir.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "def format_error" in source:  # 兜底实现自身
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "str"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in ("e", "exc")
            ):
                offenders.append(f"{path.relative_to(app_dir)}:{node.lineno}")

    assert not offenders, "这些地方仍用裸 str(e)/str(exc)，空异常消息会导致错误信息为空：" + str(offenders)
