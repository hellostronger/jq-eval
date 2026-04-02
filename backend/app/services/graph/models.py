# Graph Building Data Models
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime


class GraphEntity(BaseModel):
    """图谱实体"""
    name: str = Field(..., description="实体名称")
    entity_type: str = Field(..., description="实体类型")
    description: str = Field(..., description="实体描述")
    source_id: Optional[str] = Field(None, description="来源文档块ID")
    properties: Dict[str, Any] = Field(default_factory=dict, description="扩展属性")


class GraphRelation(BaseModel):
    """图谱关系"""
    source_entity: str = Field(..., description="源实体名称")
    target_entity: str = Field(..., description="目标实体名称")
    description: str = Field(..., description="关系描述")
    keywords: Optional[str] = Field(None, description="关系关键词")
    weight: float = Field(default=1.0, description="关系权重")
    source_id: Optional[str] = Field(None, description="来源文档块ID")
    properties: Dict[str, Any] = Field(default_factory=dict, description="扩展属性")


class KnowledgeGraphResult(BaseModel):
    """知识图谱结果"""
    entities: List[GraphEntity] = Field(default_factory=list, description="实体列表")
    relations: List[GraphRelation] = Field(default_factory=list, description="关系列表")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="元数据")


class GraphBuildRequest(BaseModel):
    """图谱构建请求 - 源文件模式"""
    text: str = Field(..., description="完整文档文本")
    doc_id: Optional[str] = Field(None, description="文档ID")
    entity_types: Optional[List[str]] = Field(None, description="指定实体类型")
    language: str = Field(default="Chinese", description="输出语言")
    chunk_size: int = Field(default=1200, description="分块大小")
    chunk_overlap: int = Field(default=100, description="分块重叠")
    options: Dict[str, Any] = Field(default_factory=dict, description="扩展选项")


class GraphChunkBuildRequest(BaseModel):
    """图谱构建请求 - 分片模式"""
    chunks: List[str] = Field(..., description="已分片的文本列表")
    doc_id: Optional[str] = Field(None, description="文档ID")
    entity_types: Optional[List[str]] = Field(None, description="指定实体类型")
    language: str = Field(default="Chinese", description="输出语言")
    options: Dict[str, Any] = Field(default_factory=dict, description="扩展选项")


class GraphBuildResult(BaseModel):
    """图谱构建结果"""
    success: bool = Field(..., description="是否成功")
    graph: Optional[KnowledgeGraphResult] = Field(None, description="图谱结果")
    error: Optional[str] = Field(None, description="错误信息")
    processing_time: float = Field(default=0.0, description="处理时间(秒)")
    chunk_count: int = Field(default=0, description="处理的分片数量")
    entity_count: int = Field(default=0, description="抽取的实体数量")
    relation_count: int = Field(default=0, description="抽取的关系数量")


class EntityExtractRequest(BaseModel):
    """实体抽取请求"""
    text: str = Field(..., description="输入文本")
    entity_types: Optional[List[str]] = Field(None, description="指定实体类型")
    language: str = Field(default="Chinese", description="输出语言")


class EntityExtractResult(BaseModel):
    """实体抽取结果"""
    success: bool = Field(..., description="是否成功")
    entities: List[GraphEntity] = Field(default_factory=list, description="抽取的实体")
    error: Optional[str] = Field(None, description="错误信息")
    processing_time: float = Field(default=0.0, description="处理时间(秒)")


class RelationExtractRequest(BaseModel):
    """关系抽取请求"""
    text: str = Field(..., description="输入文本")
    entities: List[str] = Field(..., description="已有实体名称列表")
    language: str = Field(default="Chinese", description="输出语言")


class EntityExtractResult(BaseModel):
    """实体抽取结果"""
    success: bool = Field(..., description="是否成功")
    entities: List[GraphEntity] = Field(default_factory=list, description="抽取的实体")
    error: Optional[str] = Field(None, description="错误信息")
    processing_time: float = Field(default=0.0, description="处理时间(秒)")


class RelationExtractRequest(BaseModel):
    """关系抽取请求"""
    text: str = Field(..., description="输入文本")
    entities: List[str] = Field(default_factory=list, description="已有实体名称列表")
    language: str = Field(default="Chinese", description="输出语言")


class RelationExtractResult(BaseModel):
    """关系抽取结果"""
    success: bool = Field(..., description="是否成功")
    relations: List[GraphRelation] = Field(default_factory=list, description="抽取的关系")
    error: Optional[str] = Field(None, description="错误信息")
    processing_time: float = Field(default=0.0, description="处理时间(秒)")


class GraphBuilderInfo(BaseModel):
    """图谱构建器信息"""
    builder_type: str = Field(..., description="构建器类型标识")
    display_name: str = Field(..., description="显示名称")
    description: str = Field(default="", description="描述")
    supported_languages: List[str] = Field(default=["Chinese", "English"], description="支持的语言")