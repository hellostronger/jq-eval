# 文档适配器基类
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from langchain.schema import Document
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
import logging

logger = logging.getLogger(__name__)


class DocumentAdapter(ABC):
    """文档适配器基类

    统一文档输入接口，支持多种输入源：
    - MinIO 上传文件
    - 直接文本输入
    - 已有文档选择
    """

    @abstractmethod
    async def load(self) -> List[Document]:
        """加载文档，返回 LangChain Document 格式

        Returns:
            List[Document]: LangChain 文档列表，每个文档包含 page_content 和 metadata
        """
        pass

    @abstractmethod
    def get_source_info(self) -> Dict[str, Any]:
        """获取源信息，用于日志和元数据"""
        pass


class AdapterFactory:
    """适配器工厂

    根据源类型创建对应的适配器实例
    """

    @staticmethod
    def create_adapter(
        source_type: str,
        config: Dict[str, Any],
        db: Optional[AsyncSession] = None
    ) -> DocumentAdapter:
        """创建适配器

        Args:
            source_type: 源类型，可选值：
                - "file_upload": MinIO 上传文件
                - "text_input": 直接文本输入
                - "existing_doc": 已有文档选择
            config: 配置参数，不同类型需要不同配置
            db: 数据库会话（existing_doc 类型需要）

        Returns:
            DocumentAdapter 实例

        Raises:
            ValueError: 不支持的源类型或配置缺失
        """
        if source_type == "file_upload":
            if "file_paths" not in config:
                raise ValueError("file_upload 类型需要 file_paths 配置")
            from .file_upload_adapter import FileUploadAdapter
            return FileUploadAdapter(file_paths=config["file_paths"])

        elif source_type == "text_input":
            if "texts" not in config:
                raise ValueError("text_input 类型需要 texts 配置")
            from .text_input_adapter import TextInputAdapter
            return TextInputAdapter(
                texts=config["texts"],
                metadata=config.get("metadata", {})
            )

        elif source_type == "existing_doc":
            if "document_ids" not in config:
                raise ValueError("existing_doc 类型需要 document_ids 配置")
            if db is None:
                raise ValueError("existing_doc 类型需要数据库会话")
            from .existing_doc_adapter import ExistingDocAdapter
            return ExistingDocAdapter(
                document_ids=config["document_ids"],
                db=db
            )

        else:
            raise ValueError(f"不支持的源类型: {source_type}")

    @staticmethod
    def create_multi_source_adapter(
        configs: List[Dict[str, Any]],
        db: Optional[AsyncSession] = None
    ) -> "MultiSourceAdapter":
        """创建多源适配器，支持同时从多个源加载

        Args:
            configs: 多个源配置列表
            db: 数据库会话

        Returns:
            MultiSourceAdapter 实例
        """
        adapters = []
        for config in configs:
            source_type = config.get("source_type")
            adapter = AdapterFactory.create_adapter(source_type, config, db)
            adapters.append(adapter)

        return MultiSourceAdapter(adapters)


class MultiSourceAdapter(DocumentAdapter):
    """多源适配器

    支持同时从多个源加载文档
    """

    def __init__(self, adapters: List[DocumentAdapter]):
        self.adapters = adapters

    async def load(self) -> List[Document]:
        """从所有适配器加载文档"""
        all_documents = []
        for adapter in self.adapters:
            try:
                documents = await adapter.load()
                all_documents.extend(documents)
                logger.info(f"从 {adapter.get_source_info()['type']} 加载了 {len(documents)} 个文档")
            except Exception as e:
                logger.error(f"加载文档失败: {adapter.get_source_info()}, 错误: {e}")

        return all_documents

    def get_source_info(self) -> Dict[str, Any]:
        """获取所有源信息"""
        return {
            "type": "multi_source",
            "sources": [adapter.get_source_info() for adapter in self.adapters]
        }