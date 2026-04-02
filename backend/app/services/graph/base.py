# Graph Builder Abstract Base Class
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from .models import (
    GraphEntity,
    GraphRelation,
    KnowledgeGraphResult,
    GraphBuildRequest,
    GraphChunkBuildRequest,
    GraphBuildResult,
    EntityExtractRequest,
    EntityExtractResult,
    RelationExtractRequest,
    RelationExtractResult,
)


class BaseGraphBuilder(ABC):
    """图谱构建器抽象基类"""

    builder_type: str
    display_name: str
    description: str = ""

    @abstractmethod
    async def build_from_chunks(self, request: GraphChunkBuildRequest) -> GraphBuildResult:
        """从已分片的文本列表构建图谱

        Args:
            request: 包含已分片文本列表的请求

        Returns:
            GraphBuildResult: 包含实体和关系的图谱结果
        """
        pass

    @abstractmethod
    async def build_from_document(self, request: GraphBuildRequest) -> GraphBuildResult:
        """从完整文档构建图谱（先分片再抽取）

        Args:
            request: 包含完整文档文本的请求

        Returns:
            GraphBuildResult: 包含实体和关系的图谱结果
        """
        pass

    @abstractmethod
    async def extract_entities(self, request: EntityExtractRequest) -> EntityExtractResult:
        """从文本抽取实体

        Args:
            request: 实体抽取请求

        Returns:
            EntityExtractResult: 抽取的实体列表
        """
        pass

    @abstractmethod
    async def extract_relations(
        self,
        request: RelationExtractRequest
    ) -> RelationExtractResult:
        """从文本抽取关系

        Args:
            request: 关系抽取请求（包含已有实体列表）

        Returns:
            RelationExtractResult: 抽取的关系列表
        """
        pass

    async def health_check(self) -> bool:
        """健康检查

        Returns:
            bool: 服务是否正常
        """
        return True

    def get_info(self) -> Dict[str, Any]:
        """获取构建器信息"""
        return {
            "builder_type": self.builder_type,
            "display_name": self.display_name,
            "description": self.description,
        }