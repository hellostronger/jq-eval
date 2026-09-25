# 内置指标入库：把 METRIC_REGISTRY 同步到 metric_definitions 表
#
# 指标市场的数据全部来自 metric_definitions 表，而这张表原先只有
# POST /metrics（用户自建指标）会写入——内置指标从未落库，
# 导致「指标市场」永远是空的，用户建评估时无指标可选。
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric import MetricDefinition
from app.services.metrics.engine import METRIC_REGISTRY


async def sync_builtin_metrics(db: AsyncSession) -> int:
    """把内置指标注册表同步进 metric_definitions（幂等，可重复执行）

    以 name 为唯一键：已存在的只补齐/更新描述与依赖声明等展示信息，
    不覆盖 usage_count 等运行期统计，也不新增记录；
    指标从注册表移除时把库里的记录置为 inactive，而不是物理删除
    （历史评估结果仍按 id 引用着它）。
    """
    existing = {
        row.name: row
        for row in (await db.execute(select(MetricDefinition))).scalars().all()
    }

    created = 0
    live_names = set()

    for order, (name, cls) in enumerate(METRIC_REGISTRY.items()):
        live_names.add(name)
        doc = (cls.__doc__ or "").strip().splitlines()
        description = doc[0].strip() if doc else None

        row = existing.get(name)
        if row is None:
            db.add(MetricDefinition(
                name=name,
                display_name=cls.display_name,
                description=description,
                category=cls.category,
                framework=cls.framework,
                eval_stage=cls.eval_stage,
                requires_llm=cls.requires_llm,
                requires_embedding=cls.requires_embedding,
                requires_ground_truth=cls.requires_ground_truth,
                requires_contexts=cls.requires_contexts,
                range_min=cls.range_min,
                range_max=cls.range_max,
                higher_is_better=cls.higher_is_better,
                sort_order=order,
                is_builtin=True,
                is_active=True,
                is_public=True,
            ))
            created += 1
            continue

        # 指标类上的展示信息可能被改过，跟进更新；统计字段不动
        row.display_name = cls.display_name
        row.description = description
        row.category = cls.category
        row.framework = cls.framework
        row.eval_stage = cls.eval_stage
        row.requires_llm = cls.requires_llm
        row.requires_embedding = cls.requires_embedding
        row.requires_ground_truth = cls.requires_ground_truth
        row.requires_contexts = cls.requires_contexts
        row.range_min = cls.range_min
        row.range_max = cls.range_max
        row.higher_is_better = cls.higher_is_better
        row.sort_order = order
        if not row.is_active:
            row.is_active = True

    # 注册表里已移除的内置指标：下架而不是删除，历史结果仍能查到
    for name, row in existing.items():
        if row.is_builtin and name not in live_names:
            row.is_active = False

    await db.commit()
    print(f"[OK] 内置指标已同步（新增 {created} 个，共 {len(METRIC_REGISTRY)} 个可用）")
    return created
