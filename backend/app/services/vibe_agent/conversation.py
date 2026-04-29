# VibeAgent 对话状态管理
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import json

from langchain_core.messages import HumanMessage, SystemMessage

from .prompts import (
    SLOT_GENERATION_PROMPT,
    SLOT_ANALYSIS_PROMPT,
    CLARIFICATION_PROMPT,
    SLOT_PREVIEW_PROMPT,
    SYSTEM_PROMPT,
)


@dataclass
class Slot:
    """槽位定义"""
    slot_id: str
    slot_name: str
    slot_description: str
    required: bool = True
    default_value: Optional[str] = None
    options: Optional[List[str]] = None
    current_value: Optional[str] = None
    confidence: str = "none"  # none/inferred/user_provided/auto_decide


@dataclass
class ConversationState:
    """对话状态管理"""
    session_id: str
    original_description: str
    workflow_type: Optional[str] = None
    slots: List[Slot] = field(default_factory=list)
    inferred_nodes: List[str] = field(default_factory=list)
    inferred_flow: Optional[str] = None
    current_state: str = "generating_slots"  # generating_slots/filling_slots/preview/generating/completed
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)

    def get_missing_required_slots(self) -> List[Slot]:
        """获取缺失的必要槽位"""
        return [
            slot for slot in self.slots
            if slot.required and slot.current_value is None
            and slot.confidence != "auto_decide"
        ]

    def get_filled_slots(self) -> List[Slot]:
        """获取已填充的槽位"""
        return [
            slot for slot in self.slots
            if slot.current_value is not None or slot.confidence == "auto_decide"
        ]

    def is_complete(self) -> bool:
        """检查所有必要槽位是否已填充"""
        return len(self.get_missing_required_slots()) == 0

    def get_slot_by_id(self, slot_id: str) -> Optional[Slot]:
        """根据ID获取槽位"""
        for slot in self.slots:
            if slot.slot_id == slot_id:
                return slot
        return None

    def update_slot(self, slot_id: str, value: str, confidence: str = "user_provided"):
        """更新槽位值"""
        slot = self.get_slot_by_id(slot_id)
        if slot:
            slot.current_value = value
            slot.confidence = confidence

    def add_slot(self, slot: Slot):
        """添加新槽位"""
        self.slots.append(slot)

    def add_message(self, role: str, content: str, message_type: str = "text", metadata: Dict = None):
        """添加消息到历史"""
        self.conversation_history.append({
            "role": role,
            "content": content,
            "message_type": message_type,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        })

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "original_description": self.original_description,
            "workflow_type": self.workflow_type,
            "slots": [
                {
                    "slot_id": s.slot_id,
                    "slot_name": s.slot_name,
                    "slot_description": s.slot_description,
                    "required": s.required,
                    "default_value": s.default_value,
                    "options": s.options,
                    "current_value": s.current_value,
                    "confidence": s.confidence,
                }
                for s in self.slots
            ],
            "inferred_nodes": self.inferred_nodes,
            "inferred_flow": self.inferred_flow,
            "current_state": self.current_state,
            "conversation_history": self.conversation_history,
        }


class ConversationManager:
    """对话管理器"""

    def __init__(self, llm_client):
        """
        Args:
            llm_client: LLM客户端，用于调用模型生成和分析
        """
        self.llm_client = llm_client
        self.sessions: Dict[str, ConversationState] = {}

    def create_session(self, session_id: str, description: str) -> ConversationState:
        """创建新会话"""
        state = ConversationState(
            session_id=session_id,
            original_description=description,
        )
        self.sessions[session_id] = state
        return state

    def get_session(self, session_id: str) -> Optional[ConversationState]:
        """获取会话"""
        return self.sessions.get(session_id)

    async def generate_slots(self, session_id: str) -> Dict[str, Any]:
        """
        根据用户描述动态生成槽位

        Returns:
            包含槽位列表和状态的字典
        """
        state = self.get_session(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")

        # 调用 LLM 生成槽位
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=SLOT_GENERATION_PROMPT.format(
                user_description=state.original_description
            ))
        ]

        response = await self.llm_client.ainvoke(messages)
        result = self._parse_json_response(response.content)

        # 更新状态
        state.workflow_type = result.get("workflow_type", "通用工作流")
        state.inferred_nodes = result.get("inferred_nodes", [])
        state.inferred_flow = result.get("inferred_flow")

        # 解析槽位
        for slot_data in result.get("slots", []):
            slot = Slot(
                slot_id=slot_data.get("slot_id"),
                slot_name=slot_data.get("slot_name"),
                slot_description=slot_data.get("slot_description"),
                required=slot_data.get("required", True),
                default_value=slot_data.get("default_value"),
                options=slot_data.get("options"),
                current_value=slot_data.get("current_value"),
                confidence="inferred" if slot_data.get("current_value") else "none",
            )
            state.slots.append(slot)

        state.current_state = "filling_slots"

        # 检查是否需要追问
        missing_slots = state.get_missing_required_slots()

        if missing_slots:
            # 生成追问
            clarification = await self._generate_clarification(state, missing_slots[:3])
            state.add_message("assistant", clarification, "question")
            return {
                "type": "clarification",
                "message": clarification,
                "slots": state.to_dict()["slots"],
                "missing_count": len(missing_slots),
            }
        else:
            # 槽位已完整，进入预览
            state.current_state = "preview"
            preview = await self._generate_preview(state)
            state.add_message("assistant", preview, "preview")
            return {
                "type": "preview",
                "message": preview,
                "slots": state.to_dict()["slots"],
                "ready_to_generate": True,
            }

    async def process_user_input(self, session_id: str, user_input: str) -> Dict[str, Any]:
        """
        处理用户输入，分析并更新槽位

        Returns:
            处理结果字典
        """
        state = self.get_session(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")

        # 添加用户消息
        state.add_message("user", user_input)

        # 检查用户是否想直接生成
        if self._is_generate_command(user_input):
            state.current_state = "generating"
            return {
                "type": "generate_request",
                "message": "好的，开始生成工作流...",
                "slots": state.to_dict()["slots"],
            }

        # 分析用户输入，更新槽位
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=SLOT_ANALYSIS_PROMPT.format(
                current_slots=json.dumps(state.to_dict()["slots"], ensure_ascii=False),
                user_input=user_input,
            ))
        ]

        response = await self.llm_client.ainvoke(messages)
        result = self._parse_json_response(response.content)

        # 更新槽位
        for update in result.get("slot_updates", []):
            slot_id = update.get("slot_id")
            new_value = update.get("new_value")
            confidence = update.get("confidence", "user_provided")
            state.update_slot(slot_id, new_value, confidence)

        # 添加新槽位（如果有）
        for new_slot_data in result.get("new_slots_needed", []):
            new_slot = Slot(
                slot_id=new_slot_data.get("slot_id"),
                slot_name=new_slot_data.get("slot_name"),
                slot_description=new_slot_data.get("slot_description"),
                required=new_slot_data.get("required", False),
                current_value=new_slot_data.get("current_value"),
                confidence="inferred" if new_slot_data.get("current_value") else "none",
            )
            state.add_slot(new_slot)

        # 检查是否完成
        is_complete = result.get("is_complete", False)
        missing_required = result.get("missing_required_slots", [])
        user_intent = result.get("user_intent", "补充信息")

        if is_complete or state.is_complete():
            state.current_state = "preview"
            preview = await self._generate_preview(state)
            state.add_message("assistant", preview, "preview")
            return {
                "type": "preview",
                "message": preview,
                "slots": state.to_dict()["slots"],
                "ready_to_generate": True,
            }
        else:
            # 继续追问
            missing_slots = [state.get_slot_by_id(sid) for sid in missing_required if state.get_slot_by_id(sid)]
            if not missing_slots:
                missing_slots = state.get_missing_required_slots()

            clarification = await self._generate_clarification(state, missing_slots[:3])
            state.add_message("assistant", clarification, "question")
            return {
                "type": "clarification",
                "message": clarification,
                "slots": state.to_dict()["slots"],
                "missing_count": len(missing_slots),
                "slot_updates": result.get("slot_updates", []),
            }

    async def _generate_clarification(self, state: ConversationState, missing_slots: List[Slot]) -> str:
        """生成追问消息"""
        missing_info = [
            {
                "slot_name": s.slot_name,
                "description": s.slot_description,
                "options": s.options,
                "default": s.default_value,
            }
            for s in missing_slots
        ]

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=CLARIFICATION_PROMPT.format(
                workflow_type=state.workflow_type or "工作流",
                missing_slots=json.dumps(missing_info, ensure_ascii=False),
                filled_slots=json.dumps([s.slot_name for s in state.get_filled_slots()], ensure_ascii=False),
                original_description=state.original_description,
            ))
        ]

        response = await self.llm_client.ainvoke(messages)
        return response.content.strip()

    async def _generate_preview(self, state: ConversationState) -> str:
        """生成预览消息"""
        all_slots = [
            {
                "name": s.slot_name,
                "value": s.current_value or "(未填写)",
                "confidence": s.confidence,
                "required": s.required,
            }
            for s in state.slots
        ]

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=SLOT_PREVIEW_PROMPT.format(
                all_slots=json.dumps(all_slots, ensure_ascii=False),
                workflow_type=state.workflow_type or "工作流",
            ))
        ]

        response = await self.llm_client.ainvoke(messages)
        return response.content.strip()

    def _is_generate_command(self, user_input: str) -> bool:
        """检查用户是否请求生成"""
        commands = ["生成", "开始生成", "够了", "就这样", "开始吧", "生成吧"]
        return any(cmd in user_input.lower() for cmd in commands)

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON"""
        # 尝试直接解析
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # 尝试提取 JSON 块
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            # 返回空字典
            return {}