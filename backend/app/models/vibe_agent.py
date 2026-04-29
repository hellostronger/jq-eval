# VibeAgent 模型
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, DateTime, String, Text, Integer, ForeignKey, Boolean, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from .base import BaseModel


class VibeAgentSession(BaseModel):
    """VibeAgent 对话会话"""
    __tablename__ = "vibe_agent_sessions"

    user_id = Column(UUID(as_uuid=True), nullable=True)  # 可选，用户标识
    status = Column(String(20), default="active", nullable=False)  # active/completed/aborted
    original_description = Column(Text, nullable=True)  # 用户初始描述
    conversation_history = Column(JSONB, default=list)  # 对话历史
    collected_info = Column(JSONB, default=dict)  # 收集的信息
    current_state = Column(String(20), default="gathering")  # gathering/generating/confirming/completed
    llm_config = Column(JSONB, default=dict)  # LLM配置

    # 关联的工作流
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("vibe_agent_workflows.id", ondelete="SET NULL"), nullable=True)

    def __repr__(self):
        return f"<VibeAgentSession {self.id} status={self.status}>"


class VibeAgentWorkflow(BaseModel):
    """VibeAgent 工作流定义"""
    __tablename__ = "vibe_agent_workflows"

    session_id = Column(UUID(as_uuid=True), ForeignKey("vibe_agent_sessions.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(200), nullable=False)  # 工作流名称
    description = Column(Text, nullable=True)  # 工作流描述

    # LangGraph 图定义
    graph_definition = Column(JSONB, default=dict)  # 完整的图定义（包含state定义等）
    nodes = Column(JSONB, default=list)  # 节点列表 [{id, type, name, config}]
    edges = Column(JSONB, default=list)  # 边列表 [{from, to, condition}]

    # 生成的代码和图表
    python_code = Column(Text, nullable=True)  # 生成的Python代码
    mermaid_diagram = Column(Text, nullable=True)  # Mermaid流程图

    # LLM配置（独立配置）
    llm_config = Column(JSONB, default=dict)  # {api_url, api_key, model, temperature, max_tokens}

    # 状态
    status = Column(String(20), default="draft", nullable=False)  # draft/ready/executing/completed/error
    is_active = Column(Boolean, default=True)

    # 统计
    execution_count = Column(Integer, default=0)
    version_count = Column(Integer, default=1)

    # 关系
    sessions = relationship("VibeAgentSession", foreign_keys=[session_id], backref="workflow")
    versions = relationship("VibeAgentWorkflowVersion", back_populates="workflow", cascade="all, delete-orphan")
    executions = relationship("VibeAgentExecution", back_populates="workflow", cascade="all, delete-orphan")
    node_configs = relationship("VibeAgentNodeConfig", back_populates="workflow", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<VibeAgentWorkflow {self.name}>"


class VibeAgentWorkflowVersion(BaseModel):
    """工作流版本历史"""
    __tablename__ = "vibe_agent_workflow_versions"

    workflow_id = Column(UUID(as_uuid=True), ForeignKey("vibe_agent_workflows.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)

    # 版本内容
    graph_definition = Column(JSONB, default=dict)
    nodes = Column(JSONB, default=list)
    edges = Column(JSONB, default=list)
    python_code = Column(Text, nullable=True)
    mermaid_diagram = Column(Text, nullable=True)

    # 修改信息
    change_type = Column(String(20), nullable=False)  # create/update/tune
    change_notes = Column(Text, nullable=True)  # 修改说明

    # 关系
    workflow = relationship("VibeAgentWorkflow", back_populates="versions")

    def __repr__(self):
        return f"<VibeAgentWorkflowVersion workflow_id={self.workflow_id} v{self.version}>"


class VibeAgentExecution(BaseModel):
    """工作流执行记录"""
    __tablename__ = "vibe_agent_executions"

    workflow_id = Column(UUID(as_uuid=True), ForeignKey("vibe_agent_workflows.id", ondelete="CASCADE"), nullable=False)
    workflow_version_id = Column(UUID(as_uuid=True), ForeignKey("vibe_agent_workflow_versions.id", ondelete="SET NULL"), nullable=True)

    # 输入输出
    input_data = Column(JSONB, default=dict)  # 输入参数
    output_data = Column(JSONB, default=dict)  # 输出结果
    intermediate_results = Column(JSONB, default=dict)  # 中间结果（各节点执行结果）

    # 状态
    status = Column(String(20), default="pending", nullable=False)  # pending/running/completed/failed/cancelled
    error_message = Column(Text, nullable=True)

    # 执行统计
    execution_time = Column(Float, nullable=True)  # 执行时长（秒）
    node_execution_times = Column(JSONB, default=dict)  # 各节点执行时间

    # 关系
    workflow = relationship("VibeAgentWorkflow", back_populates="executions")

    def __repr__(self):
        return f"<VibeAgentExecution workflow_id={self.workflow_id} status={self.status}>"


class VibeAgentNodeConfig(BaseModel):
    """工作流节点配置（支持参数调优）"""
    __tablename__ = "vibe_agent_node_configs"

    workflow_id = Column(UUID(as_uuid=True), ForeignKey("vibe_agent_workflows.id", ondelete="CASCADE"), nullable=False)

    # 节点标识
    node_id = Column(String(100), nullable=False)  # 节点唯一标识
    node_type = Column(String(50), nullable=False)  # llm/tool/condition/input/output/router/human
    node_name = Column(String(200), nullable=False)  # 节点名称

    # 节点配置
    config = Column(JSONB, default=dict)  # 节点具体配置
    prompt_template = Column(Text, nullable=True)  # Prompt模板（LLM节点）
    parameters = Column(JSONB, default=dict)  # 参数配置（可调优）

    # 节点输入输出定义
    input_schema = Column(JSONB, default=dict)  # 输入数据结构
    output_schema = Column(JSONB, default=dict)  # 输出数据结构

    # 执行统计
    execution_count = Column(Integer, default=0)
    avg_execution_time = Column(Float, default=0.0)
    success_rate = Column(Float, default=1.0)

    # 关系
    workflow = relationship("VibeAgentWorkflow", back_populates="node_configs")

    def __repr__(self):
        return f"<VibeAgentNodeConfig node_id={self.node_id} type={self.node_type}>"


class VibeAgentSessionMessage(BaseModel):
    """会话消息记录"""
    __tablename__ = "vibe_agent_session_messages"

    session_id = Column(UUID(as_uuid=True), ForeignKey("vibe_agent_sessions.id", ondelete="CASCADE"), nullable=False)

    # 消息内容
    role = Column(String(20), nullable=False)  # user/assistant/system
    content = Column(Text, nullable=False)

    # 消息类型
    message_type = Column(String(30), default="text")  # text/question/answer/workflow_update/error

    # 关联数据
    related_workflow_id = Column(UUID(as_uuid=True), nullable=True)
    related_node_id = Column(String(100), nullable=True)

    # 元数据
    message_metadata = Column(JSONB, default=dict)

    def __repr__(self):
        return f"<VibeAgentSessionMessage session={self.session_id} role={self.role}>"