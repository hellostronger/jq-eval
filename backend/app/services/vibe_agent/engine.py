# VibeAgent 核心引擎
from typing import Dict, Any, Optional
import json

from .conversation import ConversationManager, ConversationState
from .code_generator import LangGraphCodeGenerator
from .mermaid_generator import MermaidGenerator
from .websocket import ConnectionManager
from .executor import WorkflowExecutor, get_executor, reset_executor
from ...core.config import settings


class VibeAgentEngine:
    """VibeAgent 核心引擎"""

    def __init__(
        self,
        llm_config: Dict[str, Any] = None,
        connection_manager: ConnectionManager = None,
        use_settings: bool = True,
    ):
        """
        Args:
            llm_config: LLM 配置（可选，默认从 settings 读取）
            connection_manager: WebSocket 连接管理器
            use_settings: 是否使用配置模块（默认 True）
        """
        if use_settings and llm_config is None:
            # 从配置模块读取
            self.llm_config = {
                "api_url": settings.VIBEAGENT_LLM_URL,
                "api_key": settings.VIBEAGENT_LLM_KEY,
                "model": settings.VIBEAGENT_LLM_MODEL,
                "temperature": settings.VIBEAGENT_LLM_TEMPERATURE,
                "max_tokens": settings.VIBEAGENT_LLM_MAX_TOKENS,
            }
        else:
            self.llm_config = llm_config or self._get_default_llm_config()

        self.llm_client = self._create_llm_client()

        self.conversation_manager = ConversationManager(self.llm_client)
        self.code_generator = LangGraphCodeGenerator(self.llm_client)
        self.mermaid_generator = MermaidGenerator()
        self.connection_manager = connection_manager

        # 沙箱执行器（使用配置模块）
        self.executor = get_executor()

        # 工作流存储（内存缓存）
        self.workflow_cache: Dict[str, Dict] = {}

    def _get_default_llm_config(self) -> Dict[str, Any]:
        """获取默认 LLM 配置（备用）"""
        return {
            "api_url": settings.VIBEAGENT_LLM_URL,
            "api_key": settings.VIBEAGENT_LLM_KEY,
            "model": settings.VIBEAGENT_LLM_MODEL,
            "temperature": settings.VIBEAGENT_LLM_TEMPERATURE,
            "max_tokens": settings.VIBEAGENT_LLM_MAX_TOKENS,
        }

    def _create_llm_client(self):
        """创建 LLM 客户端"""
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=self.llm_config.get("model", "gpt-4o-mini"),
            temperature=self.llm_config.get("temperature", 0.7),
            api_key=self.llm_config.get("api_key", ""),
            base_url=self.llm_config.get("api_url", "https://api.openai.com/v1"),
            max_tokens=self.llm_config.get("max_tokens", 4000),
        )

    async def start_session(self, session_id: str, description: str) -> Dict[str, Any]:
        """开始新会话，根据用户描述生成槽位"""
        self.conversation_manager.create_session(session_id, description)
        result = await self.conversation_manager.generate_slots(session_id)
        return result

    async def process_input(self, session_id: str, user_input: str) -> Dict[str, Any]:
        """处理用户输入，更新槽位状态"""
        result = await self.conversation_manager.process_user_input(session_id, user_input)
        return result

    async def generate_workflow(self, session_id: str) -> Dict[str, Any]:
        """生成完整工作流"""
        state = self.conversation_manager.get_session(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")

        slots_data = state.to_dict()
        workflow_result = await self.code_generator.generate_from_slots(slots_data)

        workflow_def = workflow_result.get("workflow_definition", {})
        python_code = workflow_result.get("python_code", "")

        # 生成 Mermaid 流程图
        nodes = workflow_def.get("nodes", [])
        edges = workflow_def.get("edges", [])
        workflow_name = workflow_def.get("name", "工作流")

        mermaid_diagram = self.mermaid_generator.generate_flowchart(
            nodes=nodes,
            edges=edges,
            direction="TD",
            title=workflow_name
        )

        entry_point = workflow_def.get("entry_point", "input")
        if entry_point:
            mermaid_diagram = self.mermaid_generator.add_entry_point_marker(
                mermaid_diagram, entry_point
            )

        # 缓存工作流
        self.workflow_cache[session_id] = {
            "workflow_definition": workflow_def,
            "python_code": python_code,
            "mermaid_diagram": mermaid_diagram,
            "slots_data": slots_data,
        }

        state.current_state = "completed"

        return {
            "workflow_definition": workflow_def,
            "python_code": python_code,
            "mermaid_diagram": mermaid_diagram,
        }

    async def execute_workflow(self, workflow_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """在沙箱中执行工作流"""
        workflow_data = self.workflow_cache.get(workflow_id)
        if not workflow_data:
            raise ValueError(f"Workflow {workflow_id} not found")

        python_code = workflow_data.get("python_code", "")

        result = await self.executor.execute(
            python_code=python_code,
            input_data=input_data,
            llm_config=self.llm_config,
        )

        return result

    async def test_workflow(self, workflow_id: str, test_cases: list = None) -> Dict[str, Any]:
        """测试工作流代码"""
        workflow_data = self.workflow_cache.get(workflow_id)
        if not workflow_data:
            raise ValueError(f"Workflow {workflow_id} not found")

        python_code = workflow_data.get("python_code", "")
        result = await self.executor.test_code(python_code, test_cases)
        return result

    async def tune_node(self, workflow_id: str, node_id: str, feedback: Dict[str, Any]) -> Dict[str, Any]:
        """节点调优"""
        workflow_data = self.workflow_cache.get(workflow_id)
        if not workflow_data:
            raise ValueError(f"Workflow {workflow_id} not found")

        workflow_def = workflow_data.get("workflow_definition", {})
        nodes = workflow_def.get("nodes", [])

        target_node = None
        for node in nodes:
            if node.get("id") == node_id:
                target_node = node
                break

        if not target_node:
            raise ValueError(f"Node {node_id} not found in workflow")

        from .prompts import NODE_TUNING_PROMPT, SYSTEM_PROMPT
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=NODE_TUNING_PROMPT.format(
                node_type=target_node.get("type"),
                node_name=target_node.get("name"),
                current_config=json.dumps(target_node.get("config", {}), ensure_ascii=False),
                prompt_template=target_node.get("config", {}).get("prompt_template", ""),
                execution_results=json.dumps(feedback.get("execution_results", {}), ensure_ascii=False),
                problem_description=feedback.get("problem_description", ""),
            ))
        ]

        response = await self.llm_client.ainvoke(messages)
        result = self._parse_json_response(response.content)

        if result.get("parameter_adjustments"):
            target_node["config"].update(result.get("parameter_adjustments"))
        if result.get("prompt_suggestion"):
            target_node["config"]["prompt_template"] = result.get("prompt_suggestion")

        return {
            "node_id": node_id,
            "optimization_result": result,
            "updated_config": target_node.get("config"),
        }

    def get_session_state(self, session_id: str) -> Optional[ConversationState]:
        """获取会话状态"""
        return self.conversation_manager.get_session(session_id)

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """获取工作流"""
        return self.workflow_cache.get(workflow_id)

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

    def update_llm_config(self, new_config: Dict[str, Any]):
        """更新 LLM 配置"""
        self.llm_config.update(new_config)
        self.llm_client = self._create_llm_client()


# 全局引擎实例（延迟初始化）
_engine_instance: Optional[VibeAgentEngine] = None


def get_engine(llm_config: Dict = None, use_settings: bool = True) -> VibeAgentEngine:
    """获取引擎实例（使用配置模块）"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = VibeAgentEngine(llm_config=llm_config, use_settings=use_settings)
    return _engine_instance


def create_engine(llm_config: Dict, connection_manager: ConnectionManager = None) -> VibeAgentEngine:
    """创建新引擎实例（自定义配置）"""
    return VibeAgentEngine(llm_config=llm_config, connection_manager=connection_manager, use_settings=False)


def reset_engine():
    """重置引擎实例（用于配置变更后重新初始化）"""
    global _engine_instance
    _engine_instance = None
    reset_executor()