# 内置指标入库：把两个指标注册表同步到 metric_definitions 表
#
# 指标市场的数据全部来自 metric_definitions 表，而这张表原先只有
# POST /metrics（用户自建指标）会写入——内置指标从未落库，
# 导致「指标市场」永远是空的，用户建评估时无指标可选。
#
# 训练数据质量评估原先自成一套：35 个指标只活在 TRAINING_DATA_METRIC_REGISTRY 内存里，
# 从不落库，前端下拉框直接读内存注册表。后果是指标市场里看不到任何一个训练数据指标，
# 展示名/分类/阈值也没有统一的地方管。现在两个注册表一并同步，用 scope 区分，
# 指标市场成为两套体系共用的唯一数据源。
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.metric import MetricDefinition
from app.services.metrics.engine import METRIC_REGISTRY
from app.services.training_data.engine import TRAINING_DATA_METRIC_REGISTRY

# 作用域取值（写入 metric_definitions.scope）
SCOPE_RAG = "rag"
SCOPE_TRAINING_DATA = "training_data"


def _iter_builtin_metrics():
    """把两个注册表归一成统一的指标描述流（字段已对齐）

    两套基类的 compute 语义不同（QA 对 vs 训练样本），注册表保持独立；
    这里只做形状适配，不合并注册表。
    """
    order = 0
    for name, cls in METRIC_REGISTRY.items():
        doc = (cls.__doc__ or "").strip().splitlines()
        yield {
            "name": name,
            "scope": SCOPE_RAG,
            "display_name": cls.display_name,
            "description": doc[0].strip() if doc else None,
            "category": cls.category,
            "framework": cls.framework,
            "eval_stage": cls.eval_stage,
            "data_types": None,
            "default_threshold": None,
            "threshold_type": None,
            "requires_llm": cls.requires_llm,
            "requires_embedding": cls.requires_embedding,
            "requires_ground_truth": cls.requires_ground_truth,
            "requires_contexts": cls.requires_contexts,
            "range_min": cls.range_min,
            "range_max": cls.range_max,
            "higher_is_better": cls.higher_is_better,
            "sort_order": order,
        }
        order += 1

    for name, cls in TRAINING_DATA_METRIC_REGISTRY.items():
        doc = (cls.__doc__ or "").strip().splitlines()
        yield {
            "name": name,
            "scope": SCOPE_TRAINING_DATA,
            "display_name": cls.display_name,
            # 基类自带 description 字段，docstring 只作兜底
            "description": (cls.description or (doc[0].strip() if doc else "")) or None,
            "category": cls.category,
            # 训练数据指标均为自研，给固定 framework，市场里可按来源筛选
            "framework": "training_data",
            # 训练数据评估是对样本判分，不区分检索/生成阶段
            "eval_stage": "result",
            "data_types": list(cls.data_types or []),
            "default_threshold": cls.default_threshold,
            "threshold_type": cls.threshold_type,
            "requires_llm": cls.requires_llm,
            "requires_embedding": cls.requires_embedding,
            "requires_ground_truth": cls.requires_ground_truth,
            # 训练数据指标不消费检索上下文
            "requires_contexts": False,
            "range_min": cls.range_min,
            "range_max": cls.range_max,
            "higher_is_better": cls.higher_is_better,
            "sort_order": order,
        }
        order += 1


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
    seen_names = set()

    for metric in _iter_builtin_metrics():
        name = metric.pop("name")
        if name in seen_names:
            # name 是 metric_definitions 的唯一键，两套注册表撞名会导致后写的静默覆盖前者
            print(f"[WARN] 指标名 {name} 在两个注册表中重复，保留先出现的那个")
            continue
        seen_names.add(name)
        live_names.add(name)

        row = existing.get(name)
        if row is None:
            db.add(MetricDefinition(
                name=name,
                **metric,
                is_builtin=True,
                is_active=True,
                is_public=True,
            ))
            created += 1
            continue

        # 指标类上的展示信息可能被改过，跟进更新；统计字段不动
        for field, value in metric.items():
            setattr(row, field, value)
        if not row.is_active:
            row.is_active = True

    # 注册表里已移除的内置指标：下架而不是删除，历史结果仍能查到
    for name, row in existing.items():
        if row.is_builtin and name not in live_names:
            row.is_active = False

    await db.commit()
    total = len(seen_names)
    print(
        f"[OK] 内置指标已同步（RAG {len(METRIC_REGISTRY)} + 训练数据 "
        f"{len(TRAINING_DATA_METRIC_REGISTRY)}，共 {total} 个，新增 {created} 个）"
    )
    return created