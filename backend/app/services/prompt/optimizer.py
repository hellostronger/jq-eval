# Prompt 优化服务
from typing import Optional
from agent_sandbox import Sandbox


class PromptOptimizer:
    """Prompt 优化器，基于 sandbox 环境"""

    def __init__(self, sandbox_url: str = "http://localhost:8080"):
        self.sandbox_url = sandbox_url

    async def optimize(
        self,
        prompt: str,
        framework: Optional[str] = None,
        scenario: Optional[str] = None,
        target_audience: Optional[str] = None,
        constraints: Optional[str] = None
    ) -> dict:
        """
        优化 prompt

        Args:
            prompt: 原始 prompt
            framework: 指定的框架（如 RACE, CRISPE 等）
            scenario: 使用场景
            target_audience: 目标受众
            constraints: 约束条件

        Returns:
            优化后的 prompt 和说明
        """
        # 构建优化指令
        optimization_prompt = self._build_optimization_prompt(
            prompt, framework, scenario, target_audience, constraints
        )

        # 在 sandbox 中执行优化
        sandbox = Sandbox(base_url=self.sandbox_url)

        # 使用 Python 进行 prompt 优化
        code = f'''
import json

prompt = {repr(prompt)}
framework = {repr(framework)}
scenario = {repr(scenario)}
target_audience = {repr(target_audience)}
constraints = {repr(constraints)}

# 简单的 prompt 优化逻辑
optimized = prompt.strip()

# 如果指定了框架，添加框架提示
if framework:
    optimized = f"[使用 {framework} 框架]\\n\\n{{optimized}}"

# 添加场景上下文
if scenario:
    optimized = f"[场景: {{scenario}}]\\n\\n{{optimized}}"

# 添加受众提示
if target_audience:
    optimized = f"[目标受众: {{target_audience}}]\\n\\n{{optimized}}"

# 添加约束
if constraints:
    optimized = f"{{optimized}}\\n\\n[约束: {{constraints}}]"

result = {{
    "optimized_prompt": optimized,
    "framework": framework or "未指定",
    "changes": ["结构优化", "上下文补充"] if scenario or target_audience else ["格式整理"]
}}

print(json.dumps(result, ensure_ascii=False))
'''

        result = sandbox.jupyter.execute_code(code=code)

        if result.data and result.data.outputs:
            import json
            try:
                output = result.data.outputs[0].get("text", "{}")
                return json.loads(output)
            except:
                return {
                    "optimized_prompt": prompt,
                    "framework": framework or "basic",
                    "changes": ["sandbox 执行失败，返回原始 prompt"]
                }

        return {
            "optimized_prompt": prompt,
            "framework": framework or "basic",
            "changes": []
        }

    def _build_optimization_prompt(
        self,
        prompt: str,
        framework: Optional[str],
        scenario: Optional[str],
        target_audience: Optional[str],
        constraints: Optional[str]
    ) -> str:
        """构建优化指令"""
        parts = [f"原始 Prompt: {prompt}"]

        if framework:
            parts.append(f"使用框架: {framework}")
        if scenario:
            parts.append(f"使用场景: {scenario}")
        if target_audience:
            parts.append(f"目标受众: {target_audience}")
        if constraints:
            parts.append(f"约束条件: {constraints}")

        return "\n".join(parts)

    def select_framework(self, task_description: str, complexity: str = "medium") -> str:
        """根据任务描述推荐框架"""
        # 简单映射逻辑
        task_lower = task_description.lower()

        if any(word in task_lower for word in ["分析", "决策", "比较"]):
            return "RACE"
        elif any(word in task_lower for word in ["创意", "头脑风暴", "想法"]):
            return "SCAMPER"
        elif any(word in task_lower for word in ["教学", "解释", "说明"]):
            return "BAB"
        elif any(word in task_lower for word in ["写作", "文章", "内容"]):
            return "BLOG"
        elif complexity == "simple":
            return "APE"
        else:
            return "RACE"


# 全局实例
prompt_optimizer = PromptOptimizer()