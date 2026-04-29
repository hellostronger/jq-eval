# Mermaid 流程图生成器
from typing import List, Dict, Any, Optional


class MermaidGenerator:
    """Mermaid flowchart 生成器"""

    # 节点类型对应的形状定义
    NODE_SHAPES = {
        "llm": ("(", ")"),           # 圆角矩形
        "tool": ("[", "]"),          # 矩形
        "condition": ("{{", "}}"),   # 菱形
        "input": ("[/", "/]"),       # 平行四边形
        "output": ("[/", "/]"),      # 平行四边形
        "router": ("{{{{", "}}}}"),  # 六边形
        "human": ("[[", "]]"),       # 子程序形状
        "default": ("[", "]"),       # 默认矩形
    }

    # 节点颜色映射
    NODE_COLORS = {
        "llm": "#E3F2FD",      # 浅蓝色 - LLM处理
        "tool": "#FFF3E0",     # 浅橙色 - 工具/API
        "condition": "#FCE4EC", # 浅粉色 - 条件判断
        "input": "#E8F5E9",    # 浅绿色 - 输入
        "output": "#E8F5E9",   # 浅绿色 - 输出
        "router": "#F3E5F5",   # 浅紫色 - 路由
        "human": "#FFFDE7",    # 浅黄色 - 人工
        "default": "#FFFFFF",  # 默认白色
    }

    def generate_flowchart(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        direction: str = "TD",
        title: Optional[str] = None
    ) -> str:
        """
        生成 Mermaid flowchart 代码

        Args:
            nodes: 节点列表 [{id, type, name, config}]
            edges: 边列表 [{from, to, condition}]
            direction: 图方向 TD(上下)/LR(左右)/RL(右左)/BT(下上)
            title: 图表标题（可选）

        Returns:
            Mermaid flowchart 代码字符串
        """
        lines = []

        # 图表标题
        if title:
            lines.append(f"---\ntitle: {title}\n---")

        # 图表方向
        lines.append(f"graph {direction}")

        # 定义样式类
        lines.append("")
        lines.append("    %% 节点样式定义")
        for node_type, color in self.NODE_COLORS.items():
            if node_type != "default":
                lines.append(f"    classDef {node_type}Class fill:{color},stroke:#333,stroke-width:1px")

        # 定义节点
        lines.append("")
        lines.append("    %% 节点定义")
        for node in nodes:
            node_id = node.get("id", "unknown")
            node_type = node.get("type", "default")
            node_name = node.get("name", node_id)

            # 获取形状定义
            shape = self.NODE_SHAPES.get(node_type, self.NODE_SHAPES["default"])
            left, right = shape

            # 替换特殊字符避免解析错误
            safe_name = self._sanitize_name(node_name)

            # 定义节点
            lines.append(f"    {node_id}{left}\"{safe_name}\"{right}")

            # 应用样式
            if node_type in self.NODE_COLORS:
                lines.append(f"    {node_id}:::{node_type}Class")

        # 定义边
        lines.append("")
        lines.append("    %% 边定义")
        for edge in edges:
            from_id = edge.get("from", "")
            to_id = edge.get("to", "")
            condition = edge.get("condition", None)

            if condition:
                # 条件边
                safe_condition = self._sanitize_condition(condition)
                lines.append(f"    {from_id} -->|\"{safe_condition}\"| {to_id}")
            else:
                # 普通边
                lines.append(f"    {from_id} --> {to_id}")

        return "\n".join(lines)

    def _sanitize_name(self, name: str) -> str:
        """
        清理节点名称中的特殊字符
        """
        # 替换换行符和引号
        name = name.replace("\n", " ")
        name = name.replace("\"", "'")
        # 限制长度
        if len(name) > 30:
            name = name[:27] + "..."
        return name

    def _sanitize_condition(self, condition: str) -> str:
        """
        清理条件文本中的特殊字符
        """
        condition = condition.replace("\n", " ")
        condition = condition.replace("\"", "'")
        if len(condition) > 20:
            condition = condition[:17] + "..."
        return condition

    def generate_from_workflow(self, workflow: Dict[str, Any]) -> str:
        """
        从完整工作流定义生成 Mermaid 图

        Args:
            workflow: 工作流定义字典

        Returns:
            Mermaid flowchart 代码
        """
        nodes = workflow.get("nodes", [])
        edges = workflow.get("edges", [])
        name = workflow.get("name", "工作流")

        return self.generate_flowchart(
            nodes=nodes,
            edges=edges,
            direction="TD",
            title=name
        )

    def add_entry_point_marker(self, diagram: str, entry_id: str) -> str:
        """
        添加入口点标记（使用特殊节点样式）

        Args:
            diagram: 原始 Mermaid 图
            entry_id: 入口节点 ID

        Returns:
            添加了入口标记的 Mermaid 图
        """
        lines = diagram.split("\n")

        # 添加入口点样式
        entry_style_line = f"    classDef entryClass fill:#4CAF50,stroke:#2E7D32,stroke-width:2px,color:white"
        apply_style_line = f"    {entry_id}:::entryClass"

        # 找到样式定义位置后插入
        style_index = -1
        for i, line in enumerate(lines):
            if "%% 节点样式定义" in line:
                style_index = i
                break

        if style_index >= 0:
            lines.insert(style_index + 1, entry_style_line)
            # 找到节点定义后添加样式应用
            for i, line in enumerate(lines):
                if f"{entry_id}(" in line or f"{entry_id}[" in line or f"{entry_id}{{" in line:
                    lines.insert(i + 1, apply_style_line)
                    break

        return "\n".join(lines)


# 示例使用
if __name__ == "__main__":
    generator = MermaidGenerator()

    # 测试节点和边
    test_nodes = [
        {"id": "start", "type": "input", "name": "开始"},
        {"id": "llm1", "type": "llm", "name": "分析输入"},
        {"id": "cond1", "type": "condition", "name": "判断类型"},
        {"id": "tool1", "type": "tool", "name": "API调用"},
        {"id": "llm2", "type": "llm", "name": "生成回复"},
        {"id": "end", "type": "output", "name": "输出结果"},
    ]

    test_edges = [
        {"from": "start", "to": "llm1"},
        {"from": "llm1", "to": "cond1"},
        {"from": "cond1", "to": "tool1", "condition": "需要外部数据"},
        {"from": "cond1", "to": "llm2", "condition": "仅本地处理"},
        {"from": "tool1", "to": "llm2"},
        {"from": "llm2", "to": "end"},
    ]

    diagram = generator.generate_flowchart(test_nodes, test_edges, title="智能问答流程")
    print(diagram)