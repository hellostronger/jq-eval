# 预置标签配置
# 内置标签，用于各个使用场景

PRESET_TAGS = [
    # ==================== QA记录场景 ====================
    {
        "name": "异常",
        "display_name": "异常",
        "description": "标记异常的QA记录",
        "color": "#FF4D4F",
        "icon": "warning",
        "usage_scenario": "qa_record",
        "sort_order": 1
    },
    {
        "name": "待处理",
        "display_name": "待处理",
        "description": "标记待处理的QA记录",
        "color": "#FAAD14",
        "icon": "clock",
        "usage_scenario": "qa_record",
        "sort_order": 2
    },
    {
        "name": "已处理",
        "display_name": "已处理",
        "description": "标记已处理的QA记录",
        "color": "#52C41A",
        "icon": "check",
        "usage_scenario": "qa_record",
        "sort_order": 3
    },
    {
        "name": "高质量",
        "display_name": "高质量",
        "description": "标记高质量的QA记录",
        "color": "#1890FF",
        "icon": "star",
        "usage_scenario": "qa_record",
        "sort_order": 4
    },
    {
        "name": "低质量",
        "display_name": "低质量",
        "description": "标记低质量的QA记录",
        "color": "#8C8C8C",
        "icon": "minus",
        "usage_scenario": "qa_record",
        "sort_order": 5
    },

    # ==================== 数据集场景 ====================
    {
        "name": "训练集",
        "display_name": "训练集",
        "description": "标记用于训练的数据集",
        "color": "#722ED1",
        "icon": "database",
        "usage_scenario": "dataset",
        "sort_order": 1
    },
    {
        "name": "测试集",
        "display_name": "测试集",
        "description": "标记用于测试的数据集",
        "color": "#13C2C2",
        "icon": "experiment",
        "usage_scenario": "dataset",
        "sort_order": 2
    },
    {
        "name": "验证集",
        "display_name": "验证集",
        "description": "标记用于验证的数据集",
        "color": "#2F54EB",
        "icon": "verified",
        "usage_scenario": "dataset",
        "sort_order": 3
    },
    {
        "name": "公开",
        "display_name": "公开",
        "description": "标记公开可用的数据集",
        "color": "#52C41A",
        "icon": "public",
        "usage_scenario": "dataset",
        "sort_order": 4
    },
    {
        "name": "私有",
        "display_name": "私有",
        "description": "标记私有数据集",
        "color": "#FF4D4F",
        "icon": "lock",
        "usage_scenario": "dataset",
        "sort_order": 5
    },
    {
        "name": "异常",
        "display_name": "异常",
        "description": "标记异常的数据集",
        "color": "#FF4D4F",
        "icon": "warning",
        "usage_scenario": "dataset",
        "sort_order": 6
    },

    # ==================== 调用批次场景 ====================
    {
        "name": "成功",
        "display_name": "成功",
        "description": "标记成功的调用批次",
        "color": "#52C41A",
        "icon": "check-circle",
        "usage_scenario": "invocation_batch",
        "sort_order": 1
    },
    {
        "name": "失败",
        "display_name": "失败",
        "description": "标记失败的调用批次",
        "color": "#FF4D4F",
        "icon": "close-circle",
        "usage_scenario": "invocation_batch",
        "sort_order": 2
    },
    {
        "name": "异常",
        "display_name": "异常",
        "description": "标记异常的调用批次",
        "color": "#FAAD14",
        "icon": "warning",
        "usage_scenario": "invocation_batch",
        "sort_order": 3
    },
    {
        "name": "部分成功",
        "display_name": "部分成功",
        "description": "标记部分成功的调用批次",
        "color": "#1890FF",
        "icon": "info-circle",
        "usage_scenario": "invocation_batch",
        "sort_order": 4
    },
    {
        "name": "测试",
        "display_name": "测试",
        "description": "标记测试性质的调用批次",
        "color": "#13C2C2",
        "icon": "experiment",
        "usage_scenario": "invocation_batch",
        "sort_order": 5
    },
    {
        "name": "生产",
        "display_name": "生产",
        "description": "标记生产环境的调用批次",
        "color": "#722ED1",
        "icon": "rocket",
        "usage_scenario": "invocation_batch",
        "sort_order": 6
    },
]


async def init_preset_tags(db):
    """初始化预置标签"""
    from app.models.metric import Tag
    from sqlalchemy import select

    for tag_data in PRESET_TAGS:
        # 检查是否已存在（同时检查 name 和 usage_scenario）
        result = await db.execute(
            select(Tag).where(
                (Tag.name == tag_data["name"]) &
                (Tag.usage_scenario == tag_data["usage_scenario"])
            )
        )
        if result.scalar_one_or_none():
            continue

        tag = Tag(
            name=tag_data["name"],
            display_name=tag_data["display_name"],
            description=tag_data.get("description"),
            color=tag_data.get("color"),
            icon=tag_data.get("icon"),
            usage_scenario=tag_data["usage_scenario"],
            sort_order=tag_data.get("sort_order", 0),
            is_builtin=True
        )
        db.add(tag)

    await db.commit()
    print("[OK] 预置标签已初始化")