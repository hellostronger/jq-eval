# 文本输入适配器
from typing import List, Dict, Any
from langchain.schema import Document
import logging

from .base import DocumentAdapter

logger = logging.getLogger(__name__)


class TextInputAdapter(DocumentAdapter):
    """直接文本输入适配器

    支持用户直接输入文本内容，无需上传文件
    """

    def __init__(self, texts: List[str], metadata: Dict[str, Any] = None):
        """初始化

        Args:
            texts: 文本内容列表
            metadata: 自定义元数据
        """
        self.texts = texts
        self.metadata = metadata or {}

    async def load(self) -> List[Document]:
        """将文本转换为 LangChain Document"""
        documents = []

        for i, text in enumerate(self.texts):
            if not text or not text.strip():
                continue

            doc = Document(
                page_content=text.strip(),
                metadata={
                    "source": "text_input",
                    "index": i,
                    **self.metadata
                }
            )
            documents.append(doc)

        logger.info(f"从文本输入加载了 {len(documents)} 个文档")
        return documents

    def get_source_info(self) -> Dict[str, Any]:
        """获取源信息"""
        return {
            "type": "text_input",
            "text_count": len(self.texts),
            "metadata": self.metadata
        }