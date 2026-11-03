# 调用批次的取样范围
#
# 批次原先只能整数据集跑：2556 题的 MultiHop、每题几分钟的 UltraData 想
# "先试 40 题"只能再建一个小数据集绕开，同一份语料在库里留下多份副本，
# 各副本的评估口径还互不相通。
#
# 取样范围必须由 run、重试回填、终态反推共用同一份口径：
# 任何一处忘了套 limit，total_count 与实际派发条数就会不一致，
# 批次进度和"是否跑完"的判定随之失真（这正是过去卡死在 n-1/total 的成因）。
from typing import Any, Iterable, List, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.dataset import QARecord


def apply_scope(stmt, batch):
    """把批次的取样范围套到一条已按 created_at 排序的 QA 查询上。

    排序是取样可复现的前提：没有 order_by 的 limit 在不同执行计划下可能
    取到不同的行，重试就会换一批题目。
    """
    if getattr(batch, "qa_offset", None):
        stmt = stmt.offset(batch.qa_offset)
    if getattr(batch, "qa_limit", None):
        stmt = stmt.limit(batch.qa_limit)
    return stmt


async def qa_ids_in_scope(db: AsyncSession, batch) -> List[Any]:
    """批次实际要覆盖的 QA 记录 id（按 created_at 排序）"""
    rows = await db.execute(
        apply_scope(
            select(QARecord.id)
            .where(QARecord.dataset_id == batch.dataset_id)
            .order_by(QARecord.created_at),
            batch,
        )
    )
    return [r[0] for r in rows.all()]


async def count_in_scope(db: AsyncSession, batch) -> int:
    """批次应覆盖的条数：expected 与派发条数必须同口径"""
    ids = await qa_ids_in_scope(db, batch)
    return len(ids)


async def missing_qa_in_scope(
    db: AsyncSession, batch, covered_ids: Iterable[Any]
) -> Sequence[Any]:
    """取样范围内、库里还没有结果的 QA（用于重试补齐凭空消失的行）

    范围必须先于排除条件套上：把 not_in 直接拼在带 limit 的查询里，limit 会
    在排除之后才生效，于是"只跑 3 题"的批次补齐时又往外多取，把范围外的题目
    当成缺的行落进来，total_count 与实际条数再度对不上。
    """
    scoped = (
        apply_scope(
            select(QARecord.id)
            .where(QARecord.dataset_id == batch.dataset_id)
            .order_by(QARecord.created_at),
            batch,
        )
        .subquery()
    )
    stmt = select(QARecord).where(QARecord.id.in_(select(scoped.c.id)))
    covered = [c for c in covered_ids]
    if covered:
        stmt = stmt.where(QARecord.id.not_in(covered))
    rows = await db.execute(stmt.order_by(QARecord.created_at))
    return rows.scalars().all()
