# Prompt 模型
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, DateTime, String, Text, Integer, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from .base import BaseModel


class PromptVersion(BaseModel):
    """Prompt 版本记录"""
    __tablename__ = "prompt_versions"

    name = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    version = Column(Integer, default=1)
    description = Column(Text, nullable=True)
    framework = Column(String(50), nullable=True)  # 使用的框架
    parameters = Column(JSONB, default=dict)  # 框架参数
    is_active = Column(Boolean, default=True)

    # 优化相关信息
    original_prompt = Column(Text, nullable=True)  # 原始 prompt
    optimization_notes = Column(Text, nullable=True)  # 优化说明
    test_cases = Column(JSONB, default=list)  # 测试用例

    # 标签
    tags = Column(JSONB, default=list)

    # 使用场景
    usage_scenario = Column(String(50), nullable=True)

    # 统计
    usage_count = Column(Integer, default=0)
    version_count = Column(Integer, default=1)

    def __repr__(self):
        return f"<PromptVersion {self.name} v{self.version}>"


class PromptVersionHistory(BaseModel):
    """Prompt 版本历史"""
    __tablename__ = "prompt_version_history"

    prompt_version_id = Column(UUID(as_uuid=True), ForeignKey("prompt_versions.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    change_type = Column(String(20), nullable=False)  # create/update/optimize
    change_notes = Column(Text, nullable=True)

    prompt_version = relationship("PromptVersion")

    def __repr__(self):
        return f"<PromptVersionHistory {self.prompt_version_id} v{self.version}>"


class PromptFramework(BaseModel):
    """Prompt 框架定义"""
    __tablename__ = "prompt_frameworks"

    name = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    complexity = Column(String(20), nullable=False)  # simple/medium/complex
    domain = Column(String(50), nullable=True)  # 适用领域
    elements = Column(JSONB, default=list)  # 框架元素
    template = Column(Text, nullable=True)  # 框架模板
    examples = Column(JSONB, default=list)  # 使用示例
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)

    def __repr__(self):
        return f"<PromptFramework {self.name}>"