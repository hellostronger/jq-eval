# Milvus向量服务
from pymilvus import (
    connections,
    Collection,
    FieldSchema,
    CollectionSchema,
    DataType,
    utility
)
from typing import List, Dict, Any, Optional
import time

from ...core.config import settings


class MilvusService:
    """Milvus向量数据库服务"""

    def __init__(self):
        self.host = settings.MILVUS_HOST
        self.port = settings.MILVUS_PORT
        self.collection_prefix = settings.MILVUS_COLLECTION_PREFIX
        self._connected = False

    def connect(self):
        """连接Milvus"""
        if not self._connected:
            connections.connect(
                alias="default",
                host=self.host,
                port=self.port
            )
            self._connected = True

    def disconnect(self):
        """断开连接"""
        if self._connected:
            connections.disconnect("default")
            self._connected = False

    def get_collection_name(self, name: str) -> str:
        """获取完整的Collection名称"""
        return f"{self.collection_prefix}_{name}"

    def create_chunks_collection(
        self,
        dimension: int = 1536,
        description: str = "文档分片向量集合"
    ) -> Collection:
        """创建文档分片向量集合"""
        self.connect()

        collection_name = self.get_collection_name("chunks")

        # 检查是否已存在
        if utility.has_collection(collection_name):
            return Collection(collection_name)

        # 定义字段
        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=100, is_primary=True),
            FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=100),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=8000),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dimension),
            FieldSchema(name="chunk_index", dtype=DataType.INT64),
            FieldSchema(name="created_at", dtype=DataType.INT64),
        ]

        # 创建Schema
        schema = CollectionSchema(fields=fields, description=description)

        # 创建Collection
        collection = Collection(name=collection_name, schema=schema)

        # 创建向量索引
        index_params = {
            "metric_type": "COSINE",
            "index_type": "IVF_FLAT",
            "params": {"nlist": 1024}
        }
        collection.create_index(field_name="embedding", index_params=index_params)

        return collection

    def get_chunks_collection(self) -> Optional[Collection]:
        """获取文档分片向量集合"""
        self.connect()

        collection_name = self.get_collection_name("chunks")
        if utility.has_collection(collection_name):
            return Collection(collection_name)
        return None

    def insert_chunks(
        self,
        data: List[Dict[str, Any]]
    ) -> List[str]:
        """插入分片向量"""
        collection = self.get_chunks_collection()
        if not collection:
            raise ValueError("Chunks collection不存在，请先创建")

        # 准备数据
        ids = [str(d["id"]) for d in data]
        doc_ids = [str(d.get("doc_id", "")) for d in data]
        contents = [d.get("content", "")[:8000] for d in data]
        embeddings = [d["embedding"] for d in data]
        chunk_indexes = [d.get("chunk_index", 0) for d in data]
        created_ats = [int(time.time()) for _ in data]

        # 插入数据
        collection.insert([
            ids,
            doc_ids,
            contents,
            embeddings,
            chunk_indexes,
            created_ats
        ])
        collection.flush()

        return ids

    def search_chunks(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        doc_ids: Optional[List[str]] = None,
        filter_expr: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """搜索相似分片"""
        collection = self.get_chunks_collection()
        if not collection:
            return []

        # 加载到内存
        collection.load()

        # 构建过滤表达式
        expr = None
        if doc_ids:
            doc_ids_str = ",".join([f'"{d}"' for d in doc_ids])
            expr = f"doc_id in [{doc_ids_str}]"
        if filter_expr:
            if expr:
                expr = f"({expr}) and ({filter_expr})"
            else:
                expr = filter_expr

        # 搜索参数
        search_params = {
            "metric_type": "COSINE",
            "params": {"nprobe": 10}
        }

        # 执行搜索
        results = collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=["id", "doc_id", "content", "chunk_index"]
        )

        # 处理结果
        chunks = []
        for hits in results:
            for hit in hits:
                chunks.append({
                    "id": hit.entity.get("id"),
                    "doc_id": hit.entity.get("doc_id"),
                    "content": hit.entity.get("content"),
                    "chunk_index": hit.entity.get("chunk_index"),
                    "score": hit.score,
                    "distance": hit.distance
                })

        return chunks

    def delete_chunks_by_doc(self, doc_id: str) -> int:
        """删除文档的所有分片"""
        collection = self.get_chunks_collection()
        if not collection:
            return 0

        expr = f'doc_id == "{doc_id}"'
        collection.delete(expr)
        collection.flush()

        return 1

    def delete_chunks_by_ids(self, chunk_ids: List[str]) -> int:
        """删除指定分片"""
        collection = self.get_chunks_collection()
        if not collection:
            return 0

        ids_str = ",".join([f'"{i}"' for i in chunk_ids])
        expr = f'id in [{ids_str}]'
        collection.delete(expr)
        collection.flush()

        return len(chunk_ids)

    def get_collection_stats(self) -> Dict[str, Any]:
        """获取Collection统计信息"""
        collection = self.get_chunks_collection()
        if not collection:
            return {"exists": False}

        collection.load()
        stats = collection.num_entities

        return {
            "exists": True,
            "name": collection.name,
            "num_entities": stats
        }

    def list_collections(self) -> List[str]:
        """列出所有collections"""
        self.connect()
        return utility.list_collections()

    def drop_chunks_collection(self):
        """删除文档分片向量集合"""
        self.connect()

        collection_name = self.get_collection_name("chunks")
        if utility.has_collection(collection_name):
            utility.drop_collection(collection_name)


# 单例
_milvus_service: Optional[MilvusService] = None


def get_milvus_service() -> MilvusService:
    """获取Milvus服务单例"""
    global _milvus_service
    if _milvus_service is None:
        _milvus_service = MilvusService()
    return _milvus_service


def get_milvus_client() -> MilvusService:
    """获取Milvus客户端实例"""
    return get_milvus_service()


# 别名，保持向后兼容
MilvusClient = MilvusService