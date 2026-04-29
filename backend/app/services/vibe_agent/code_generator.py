# LangGraph 代码生成器
from typing import Dict, Any, List, Optional
import json

from langchain_core.messages import HumanMessage, SystemMessage

from .prompts import CODE_GENERATION_PROMPT, WORKFLOW_GENERATION_PROMPT, SYSTEM_PROMPT


class LangGraphCodeGenerator:
    """LangGraph Python 代码生成器"""

    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLM客户端（可选，如果提供则使用LLM生成代码）
        """
        self.llm_client = llm_client

    async def generate_from_slots(self, slots_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        从槽位数据生成工作流定义和代码

        Args:
            slots_data: 包含槽位、工作流类型等信息

        Returns:
            包含 workflow_definition 和 python_code 的字典
        """
        if self.llm_client:
            return await self._generate_with_llm(slots_data)
        else:
            return self._generate_template(slots_data)

    async def _generate_with_llm(self, slots_data: Dict[str, Any]) -> Dict[str, Any]:
        """使用 LLM 生成工作流"""
        # 第一步：生成工作流定义
        workflow_messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=WORKFLOW_GENERATION_PROMPT.format(
                workflow_type=slots_data.get("workflow_type", "通用工作流"),
                slots=json.dumps(slots_data.get("slots", []), ensure_ascii=False),
                inferred_nodes=slots_data.get("inferred_nodes", []),
                inferred_flow=slots_data.get("inferred_flow", "顺序执行"),
            ))
        ]

        workflow_response = await self.llm_client.ainvoke(workflow_messages)
        workflow_definition = self._parse_json_response(workflow_response.content)

        # 第二步：生成 Python 代码
        code_messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=CODE_GENERATION_PROMPT.format(
                workflow_definition=json.dumps(workflow_definition, ensure_ascii=False),
            ))
        ]

        python_response = await self.llm_client.ainvoke(code_messages)
        python_code = self._clean_code(python_response.content)

        return {
            "workflow_definition": workflow_definition,
            "python_code": python_code,
        }

    def _generate_template(self, slots_data: Dict[str, Any]) -> Dict[str, Any]:
        """使用模板生成基础工作流（无LLM时的备用方案）"""
        slots = slots_data.get("slots", [])
        workflow_name = self._get_slot_value(slots, "workflow_name", "自定义工作流")
        workflow_type = slots_data.get("workflow_type", "通用工作流")

        # 根据工作流类型生成基础模板
        workflow_definition = self._create_basic_workflow(workflow_name, workflow_type, slots)
        python_code = self._generate_basic_code(workflow_definition)

        return {
            "workflow_definition": workflow_definition,
            "python_code": python_code,
        }

    def _create_basic_workflow(self, name: str, workflow_type: str, slots: List[Dict]) -> Dict[str, Any]:
        """创建基础工作流定义"""
        nodes = []
        edges = []

        # 根据类型添加基础节点
        if workflow_type in ["问答", "智能客服"]:
            nodes = [
                {"id": "input", "type": "input", "name": "接收问题", "config": {}},
                {"id": "llm_process", "type": "llm", "name": "LLM处理", "config": {"prompt_template": "回答用户问题"}},
                {"id": "output", "type": "output", "name": "输出回答", "config": {}},
            ]
            edges = [
                {"from": "input", "to": "llm_process"},
                {"from": "llm_process", "to": "output"},
            ]
        elif workflow_type in ["数据处理", "数据清洗"]:
            nodes = [
                {"id": "input", "type": "input", "name": "接收数据", "config": {}},
                {"id": "process", "type": "tool", "name": "数据处理", "config": {}},
                {"id": "output", "type": "output", "name": "输出结果", "config": {}},
            ]
            edges = [
                {"from": "input", "to": "process"},
                {"from": "process", "to": "output"},
            ]
        else:
            # 默认简单流程
            nodes = [
                {"id": "input", "type": "input", "name": "输入", "config": {}},
                {"id": "process", "type": "llm", "name": "处理", "config": {}},
                {"id": "output", "type": "output", "name": "输出", "config": {}},
            ]
            edges = [
                {"from": "input", "to": "process"},
                {"from": "process", "to": "output"},
            ]

        return {
            "name": name,
            "description": f"{workflow_type}工作流",
            "nodes": nodes,
            "edges": edges,
            "state_schema": {
                "input": "str",
                "output": "str",
                "context": "dict",
            },
            "entry_point": "input",
        }

    def _generate_basic_code(self, workflow_def: Dict[str, Any]) -> str:
        """生成基础 Python 代码"""
        name = workflow_def.get("name", "workflow")
        nodes = workflow_def.get("nodes", [])
        edges = workflow_def.get("edges", [])
        entry_point = workflow_def.get("entry_point", "input")

        code_lines = [
            "# LangGraph 工作流代码",
            f"# 工作流名称: {name}",
            "",
            "from typing import TypedDict, Annotated",
            "from langgraph.graph import StateGraph, END",
            "",
            "# 状态定义",
            "class WorkflowState(TypedDict):",
            "    input: str",
            "    output: str",
            "    context: dict",
            "",
        ]

        # 生成节点函数
        for node in nodes:
            node_id = node["id"]
            node_type = node["type"]
            node_name = node["name"]

            code_lines.append(f"# {node_name} 节点")
            code_lines.append(f"def {node_id}_node(state: WorkflowState) -> WorkflowState:")
            code_lines.append(f"    \"\"\"{node_name}处理\"\"\"")

            if node_type == "input":
                code_lines.append("    # 接收输入")
                code_lines.append("    return state")
            elif node_type == "llm":
                code_lines.append("    # LLM 处理逻辑（待实现）")
                code_lines.append("    # TODO: 调用 LLM API")
                code_lines.append("    state['output'] = '处理结果'")
                code_lines.append("    return state")
            elif node_type == "tool":
                code_lines.append("    # 工具调用逻辑（待实现）")
                code_lines.append("    # TODO: 执行工具/API")
                code_lines.append("    return state")
            elif node_type == "output":
                code_lines.append("    # 输出结果")
                code_lines.append("    return state")
            else:
                code_lines.append("    # 处理逻辑")
                code_lines.append("    return state")
            code_lines.append("")

        # 构建图
        code_lines.append("# 构建工作流图")
        code_lines.append(f"workflow = StateGraph(WorkflowState)")
        for node in nodes:
            code_lines.append(f"workflow.add_node('{node['id']}', {node['id']}_node)")
        code_lines.append("")

        # 添加边
        for edge in edges:
            from_id = edge["from"]
            to_id = edge["to"]
            condition = edge.get("condition")

            if condition:
                code_lines.append(f"# 条件边: {from_id} -> {to_id} (条件: {condition})")
                code_lines.append(f"# workflow.add_conditional_edges('{from_id}', ...)")
            else:
                code_lines.append(f"workflow.add_edge('{from_id}', '{to_id}')")
        code_lines.append("")

        # 设置入口点
        code_lines.append(f"workflow.set_entry_point('{entry_point}')")
        code_lines.append("")

        # 编译和执行
        code_lines.append("# 编译图")
        code_lines.append("app = workflow.compile()")
        code_lines.append("")
        code_lines.append("# 执行入口")
        code_lines.append("def execute(input_data: str) -> dict:")
        code_lines.append("    \"\"\"执行工作流\"\"\"")
        code_lines.append("    initial_state = WorkflowState(input=input_data, output='', context={})")
        code_lines.append("    result = app.invoke(initial_state)")
        code_lines.append("    return result")
        code_lines.append("")
        code_lines.append("# 示例调用")
        code_lines.append("# result = execute('测试输入')")
        code_lines.append("# print(result)")

        return "\n".join(code_lines)

    def _get_slot_value(self, slots: List[Dict], slot_id: str, default: str = "") -> str:
        """获取槽位值"""
        for slot in slots:
            if slot.get("slot_id") == slot_id:
                return slot.get("current_value") or slot.get("default_value") or default
        return default

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析 JSON 响应"""
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            return {}

    def _clean_code(self, code: str) -> str:
        """清理代码中的 markdown 标记"""
        # 去掉 ```python 和 ``` 标记
        code = code.replace("```python", "").replace("```", "")
        # 去掉前后空白
        code = code.strip()
        return code


# 代码模板片段
NODE_TEMPLATES = {
    "llm": """
def llm_node(state: WorkflowState) -> WorkflowState:
    \"\"\"LLM 处理节点\"\"\"from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model="{model}",
        temperature={temperature},
        api_key="{api_key}",
        base_url="{api_url}"
    )

    prompt = \"{prompt_template}\"
    response = llm.invoke(prompt + state['input'])
    state['context']['llm_response'] = response.content
    return state
""",
    "tool": """
def tool_node(state: WorkflowState) -> WorkflowState:
    \"\"\"工具调用节点\"\"\"import httpx

    # API 调用配置
    api_url = \"{api_url}\"
    params = {params}

    response = httpx.post(api_url, json=params)
    result = response.json()
    state['context']['tool_result'] = result
    return state
""",
    "condition": """
def condition_node(state: WorkflowState) -> str:
    \"\"\"条件判断节点\"\"\"# 返回下一个节点 ID
    condition_value = state['context'].get('{check_field}')
    if condition_value == '{condition_value_1}':
        return '{target_node_1}'
    else:
        return '{target_node_2}'
""",
    "human": """
def human_node(state: WorkflowState) -> WorkflowState:
    \"\"\"人工介入节点\"\"\"# 等待人工输入
    human_input = input(\"{prompt}: \")
    state['context']['human_input'] = human_input
    return state
""",
}