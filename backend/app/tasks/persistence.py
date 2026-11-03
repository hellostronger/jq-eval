# 长任务的落库韧性
#
# 远端 PG/Redis 随时会掐线（实测反复出现 asyncpg ConnectionDoesNotExistError），
# 而一次 RAG 调用/一个 ragas 指标动辄几分钟。用调用方那条长 session 提交，
# 断了就是整批回滚——几分钟的 Token 白花，任务还被判成失败。
# 调用批次（invocation_tasks）和评估（evaluation_tasks）都要走同一套
# "换新 session 重试"的写法，所以逻辑放在这里，不在两个任务模块里各写一份。
import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# session 工厂：无参调用返回一个 async context manager 形态的 session
SessionFactory = Callable[[], Awaitable]


async def commit_with_retry(
    apply: Callable,
    *,
    get_session: SessionFactory,
    label: str = "写入",
    context: str = "",
    attempts: int = 3,
    base_delay: float = 1.5,
):
    """在一个独立短事务里执行 apply(db) 并提交，失败就换新 session 重来。

    apply 必须做成幂等的（先删后插，或按主键覆盖）：重试时上一次可能已经写成功一半，
    不幂等就会在结果表里留下重复行，均值被同一条样本重复计入。

    返回 apply 的返回值（终态收敛这类写法需要把结果读回来）。
    """
    last_exc = None
    for attempt in range(attempts):
        try:
            async with get_session() as db:
                result = await apply(db)
                await db.commit()
            return result
        except Exception as exc:
            last_exc = exc
            logger.warning(
                f"{label}失败（第 {attempt + 1}/{attempts} 次）{context}: {exc}"
            )
            await asyncio.sleep(base_delay * (attempt + 1))
    raise last_exc
