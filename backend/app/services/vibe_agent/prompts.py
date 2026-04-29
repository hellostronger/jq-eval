# VibeAgent Prompt 模板

# 系统角色定义
SYSTEM_PROMPT = """你是一个智能工作流助手 VibeAgent，帮助用户通过 LangGraph 构建自动化工作流。

## 工作原理

采用"槽位确认"机制：
1. 根据用户描述动态生成待确认的槽位（slots）
2. 分析每个槽位的填充状态
3. 对未填充的槽位追问用户
4. 槽位全部填充后生成工作流

## LangGraph 节点类型

1. **LLM节点**：调用大语言模型处理文本
2. **Tool节点**：执行外部工具或 API 调用
3. **Condition节点**：条件判断分支
4. **Input节点**：接收用户输入或外部数据
5. **Output节点**：输出结果
6. **Router节点**：路由分发
7. **Human节点**：等待人工介入

## 交互原则

- 每次追问最多 2-3 个关键问题
- 根据工作流类型动态生成槽位，不同工作流需要不同信息
- 槽位填充后可随时预览部分流程图
- 用户可手动跳过某些槽位（标记为"用户自行决定"）
"""

# 槽位动态生成 Prompt
SLOT_GENERATION_PROMPT = """根据用户对工作流的描述，动态生成需要确认的槽位列表。

用户描述：
{user_description}

请分析用户意图，判断这是什么类型的工作流，然后生成该类型工作流需要的槽位。

输出 JSON 格式：
{
    "workflow_type": "工作流类型（如：问答/数据处理/自动化流程/智能客服等）",
    "slots": [
        {
            "slot_id": "唯一标识",
            "slot_name": "槽位名称（中文）",
            "slot_description": "槽位说明",
            "required": true/false,
            "default_value": "默认值（可选）",
            "options": ["选项1", "选项2"] 或 null,
            "current_value": null 或 "已推断的值"
        }
    ],
    "inferred_nodes": ["推断可能需要的节点类型列表"],
    "inferred_flow": "推断的流程大致走向"
}

槽位生成原则：
1. 不同工作流类型需要不同的槽位，不要用固定模板
2. 从用户描述中推断的值填入 current_value
3. 必要槽位(required=true)通常包括：名称、输入、输出
4. 可选槽位(required=false)可让用户跳过
5. 槽位数量控制在 5-10 个，避免过多

示例：
- 问答类工作流槽位：知识库来源、LLM模型、回答风格、是否需要引用
- 数据处理类槽位：数据源、处理规则、输出格式、是否需要验证
- 自动化流程槽位：触发条件、执行步骤、失败处理、通知方式
"""

# 槽位状态分析 Prompt
SLOT_ANALYSIS_PROMPT = """分析用户最新输入，更新槽位填充状态。

当前槽位状态：
{current_slots}

用户最新输入：
{user_input}

请分析用户输入是否填充了某些槽位，并更新槽位状态。

输出 JSON 格式：
{
    "slot_updates": [
        {
            "slot_id": "槽位ID",
            "new_value": "新值",
            "confidence": "high/medium/low（置信度）",
            "update_reason": "更新原因"
        }
    ],
    "new_slots_needed": [
        // 根据用户输入发现需要新增的槽位
    ],
    "is_complete": true/false,
    "missing_required_slots": ["缺失的必要槽位ID列表"],
    "user_intent": "用户意图分析（如：补充信息/修改需求/确认生成等）"
}

注意：
- 如果用户说"不确定"、"你定吧"等，可将槽位设为 default_value 或标记为 "auto_decide"
- 如果用户补充了新信息，可能需要新增槽位
- 如果用户明确说"开始生成"、"够了"等，设置 is_complete=true
"""

# 追问生成 Prompt
CLARIFICATION_PROMPT = """根据缺失的槽位，生成追问消息。

工作流类型：{workflow_type}

缺失槽位：
{missing_slots}

已填充槽位：
{filled_slots}

用户原始描述：
{original_description}

请生成一段自然、礼貌的追问消息（中文）。

追问原则：
1. 一次最多问 2-3 个问题
2. 先问最关键的必要槽位
3. 提供选项时列出可能的选择
4. 如果槽位有默认值，可以告诉用户"如果不指定，将使用默认值xxx"
5. 格式自然，像对话而不是问卷

直接输出追问文本，不要包含 JSON 或格式标记。
"""

# 工作流生成 Prompt
WORKFLOW_GENERATION_PROMPT = """根据填充完成的槽位，生成 LangGraph 工作流定义。

## 工作流类型
{workflow_type}

## 槽位信息
{slots}

## 推断信息
- 可能节点类型：{inferred_nodes}
- 流程走向：{inferred_flow}

请生成完整的工作流定义，输出 JSON 格式：

```json
{
    "name": "工作流名称",
    "description": "工作流描述",
    "nodes": [
        {
            "id": "node_id",
            "type": "node_type（llm/tool/condition/input/output/router/human）",
            "name": "节点名称",
            "config": {
                // 节点具体配置
                // LLM节点：prompt_template, model, temperature
                // Tool节点：tool_name, api_url, params
                // Condition节点：conditions [{expression, target_node}]
                // Human节点：prompt, timeout
            }
        }
    ],
    "edges": [
        {
            "from": "source_node_id",
            "to": "target_node_id",
            "condition": "条件表达式（仅条件边需要）"
        }
    ],
    "state_schema": {
        // 状态字段定义
    },
    "entry_point": "起始节点id"
}
```

确保：
1. 每个节点有唯一 id
2. 边连接正确，无孤立节点
3. 有明确的入口和输出节点
4. 槽位信息正确映射到节点配置
"""

# Mermaid 生成 Prompt
MERMAID_GENERATION_PROMPT = """根据工作流定义，生成 Mermaid flowchart 代码。

工作流节点：
{nodes}

工作流边：
{edges}

请生成 Mermaid flowchart 代码，使用以下格式：
- 使用 graph TD（从上到下）
- LLM节点使用圆角矩形：id(\"节点名称\")
- Tool节点使用矩形：id[节点名称]
- Condition节点使用菱形：id{{节点名称}}
- Input/Output节点使用平行四边形：id[/节点名称/]
- Router节点使用六边形：id{{{{节点名称}}}}
- Human节点使用子程序形状：id[[节点名称]]
- 边使用箭头：A --> B 或 A -->|条件文本| B

直接输出 Mermaid 代码，不要包含其他解释。
"""

# Python 代码生成 Prompt
CODE_GENERATION_PROMPT = """根据工作流定义，生成可执行的 LangGraph Python 代码。

工作流定义：
{workflow_definition}

请生成完整的 Python 代码，包含：
1. 必要的导入语句
2. 状态定义（使用 TypedDict）
3. 各节点的处理函数
4. StateGraph 的构建和编译
5. 执行入口函数

代码要求：
- 使用 typing.TypedDict 定义状态
- 每个节点函数有清晰注释
- 使用 langgraph.graph.StateGraph 构建图
- 正确处理条件边（使用 add_conditional_edges）
- 提供 execute() 函数作为入口

直接输出 Python 代码，不要包含其他解释。
"""

# 节点调优 Prompt
NODE_TUNING_PROMPT = """分析节点执行结果，提供优化建议。

节点信息：
- 节点类型：{node_type}
- 节点名称：{node_name}
- 当前配置：{current_config}
- Prompt模板：{prompt_template}
- 执行结果：{execution_results}
- 问题描述：{problem_description}

请提供优化建议，输出 JSON 格式：
{
    "prompt_suggestion": "Prompt优化建议（如为LLM节点）",
    "parameter_adjustments": {
        "temperature": 0.7,
        // 其他参数调整
    },
    "logic_improvements": [
        "逻辑改进建议1",
        "逻辑改进建议2"
    ],
    "expected_improvement": "预期改进效果"
}
"""

# 槽位预览确认 Prompt
SLOT_PREVIEW_PROMPT = """生成槽位确认预览消息。

当前所有槽位：
{all_slots}

工作流类型：{workflow_type}

请生成一个简洁的确认消息，列出所有槽位及其当前值，格式如下：

📋 当前工作流配置预览：

**工作流类型**：xxx
**工作流名称**：xxx

| 配置项 | 当前值 | 状态 |
|--------|--------|------|
| 输入类型 | xxx | ✅ 已确认 |
| 输出类型 | xxx | ⏳ 待确认 |
| ... | ... | ... |

还有 {missing_count} 个必要配置项需要确认。
是否继续补充，或者直接开始生成？（输入"生成"可直接开始）
"""