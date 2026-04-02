# 数据同步适配器实现
import asyncpg
import json
from typing import Dict, List, Any, Optional, AsyncIterator
from datetime import datetime

from .base import (
    BaseSyncAdapter,
    SyncConfig,
    SchemaInfo,
    FieldMapping,
)


class DifySyncAdapter(BaseSyncAdapter):
    """Dify数据同步适配器"""

    source_type = "database"
    system_type = "dify"
    display_name = "Dify"

    DEFAULT_MAPPINGS = {
        "chunks": [
            FieldMapping(source_field="id", target_field="id"),
            FieldMapping(source_field="document_id", target_field="doc_id"),
            FieldMapping(source_field="content", target_field="content"),
            FieldMapping(source_field="position", target_field="chunk_index"),
            FieldMapping(source_field="word_count", target_field="metadata.word_count"),
            FieldMapping(source_field="keywords", target_field="metadata.keywords"),
            FieldMapping(source_field="created_at", target_field="created_at", transform="to_datetime"),
        ],
        "qa_records": [
            FieldMapping(source_field="id", target_field="id"),
            FieldMapping(source_field="query", target_field="question"),
            FieldMapping(source_field="answer", target_field="answer"),
            FieldMapping(source_field="retriever_resources", target_field="contexts", transform="extract_retriever_contexts"),
            FieldMapping(source_field="created_at", target_field="created_at", transform="to_datetime"),
        ],
    }

    async def connect(self) -> bool:
        try:
            self._connection = await asyncpg.connect(
                host=self.connection_config["host"],
                port=self.connection_config.get("port", 5432),
                database=self.connection_config["database"],
                user=self.connection_config["username"],
                password=self.connection_config["password"]
            )
            return True
        except Exception as e:
            raise ConnectionError(f"Dify数据库连接失败: {e}")

    async def disconnect(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def test_connection(self) -> Dict[str, Any]:
        try:
            await self.connect()
            tables = await self.get_tables()
            dify_tables = ["document_segments", "messages", "documents"]
            is_dify = any(t in tables for t in dify_tables)
            await self.disconnect()
            return {
                "success": True,
                "is_dify_database": is_dify,
                "tables_found": [t for t in dify_tables if t in tables]
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_schema(self) -> List[SchemaInfo]:
        schemas = []
        for table in ["document_segments", "messages", "documents"]:
            schema = await self._get_table_schema(table)
            schemas.append(SchemaInfo(
                table_name=table,
                columns=schema,
                row_count=await self._count_table(table)
            ))
        return schemas

    async def _get_table_schema(self, table_name: str) -> List[Dict[str, Any]]:
        query = """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns WHERE table_name = $1
        """
        rows = await self._connection.fetch(query, table_name)
        return [{"name": r["column_name"], "type": r["data_type"]} for r in rows]

    async def _count_table(self, table_name: str) -> int:
        return await self._connection.fetchval(f"SELECT COUNT(*) FROM {table_name}")

    async def get_tables(self) -> List[str]:
        query = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        rows = await self._connection.fetch(query)
        return [r["table_name"] for r in rows]

    async def fetch_data(
        self,
        table: str,
        config: SyncConfig
    ) -> AsyncIterator[Dict[str, Any]]:
        base_query = f"SELECT * FROM {table}"
        conditions = []
        params = []

        if config.incremental and config.since:
            conditions.append("created_at > $1")
            params.append(config.since)

        query = base_query
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += f" ORDER BY created_at ASC LIMIT {config.batch_size}"

        offset = 0
        while True:
            offset_query = f"{query} OFFSET {offset}"
            if params:
                rows = await self._connection.fetch(offset_query, *params)
            else:
                rows = await self._connection.fetch(offset_query)

            if not rows:
                break

            for row in rows:
                yield dict(row)

            offset += config.batch_size

    def get_default_mappings(self) -> Dict[str, List[FieldMapping]]:
        return self.DEFAULT_MAPPINGS

    def _apply_transform(self, value: Any, transform: str) -> Any:
        if transform == "extract_retriever_contexts":
            if value and isinstance(value, str):
                try:
                    data = json.loads(value)
                    return [doc.get("content", "") for doc in data.get("documents", [])]
                except:
                    return []
            return []
        return super()._apply_transform(value, transform)


class FastGPTSyncAdapter(BaseSyncAdapter):
    """FastGPT数据同步适配器（MongoDB）"""

    source_type = "database"
    system_type = "fastgpt"
    display_name = "FastGPT"

    async def connect(self) -> bool:
        from motor.motor_asyncio import AsyncIOMotorClient
        try:
            self._client = AsyncIOMotorClient(self.connection_config["uri"])
            self._db = self._client[self.connection_config["database"]]
            await self._db.list_collection_names()
            return True
        except Exception as e:
            raise ConnectionError(f"FastGPT MongoDB连接失败: {e}")

    async def disconnect(self) -> None:
        if self._client:
            self._client.close()

    async def test_connection(self) -> Dict[str, Any]:
        try:
            await self.connect()
            collections = await self.get_tables()
            is_fastgpt = any(c in collections for c in ["kb_data", "chat"])
            await self.disconnect()
            return {"success": True, "is_fastgpt_database": is_fastgpt}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_schema(self) -> List[SchemaInfo]:
        schemas = []
        for coll in ["kb_data", "chat"]:
            sample = await self._db[coll].find_one()
            columns = [{"name": k, "type": str(type(v).__name__)} for k, v in (sample or {}).items()]
            count = await self._db[coll].count_documents({})
            schemas.append(SchemaInfo(table_name=coll, columns=columns, row_count=count))
        return schemas

    async def get_tables(self) -> List[str]:
        return await self._db.list_collection_names()

    async def fetch_data(self, table: str, config: SyncConfig) -> AsyncIterator[Dict[str, Any]]:
        filter_query = {}
        if config.incremental and config.since:
            filter_query["createTime"] = {"$gt": config.since}

        cursor = self._db[table].find(filter_query)
        for doc in cursor:
            yield doc

    def get_default_mappings(self) -> Dict[str, List[FieldMapping]]:
        return {
            "chunks": [
                FieldMapping(source_field="_id", target_field="id"),
                FieldMapping(source_field="chunks", target_field="content"),
            ],
            "qa_records": [
                FieldMapping(source_field="messages", target_field="qa_pairs"),
            ]
        }


class N8nSyncAdapter(BaseSyncAdapter):
    """n8n数据同步适配器"""

    source_type = "database"
    system_type = "n8n"
    display_name = "n8n"

    async def connect(self) -> bool:
        self._connection = await asyncpg.connect(
            host=self.connection_config["host"],
            port=self.connection_config.get("port", 5432),
            database=self.connection_config["database"],
            user=self.connection_config["username"],
            password=self.connection_config["password"]
        )
        return True

    async def disconnect(self) -> None:
        if self._connection:
            await self._connection.close()

    async def test_connection(self) -> Dict[str, Any]:
        try:
            await self.connect()
            tables = await self.get_tables()
            is_n8n = "execution_entity" in tables
            await self.disconnect()
            return {"success": True, "is_n8n_database": is_n8n}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_schema(self) -> List[SchemaInfo]:
        schema = await self._get_table_schema("execution_entity")
        count = await self._count_table("execution_entity")
        return [SchemaInfo(table_name="execution_entity", columns=schema, row_count=count)]

    async def _get_table_schema(self, table: str) -> List[Dict[str, Any]]:
        query = "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = $1"
        rows = await self._connection.fetch(query, table)
        return [{"name": r["column_name"], "type": r["data_type"]} for r in rows]

    async def _count_table(self, table: str) -> int:
        return await self._connection.fetchval(f"SELECT COUNT(*) FROM {table}")

    async def get_tables(self) -> List[str]:
        query = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        rows = await self._connection.fetch(query)
        return [r["table_name"] for r in rows]

    async def fetch_data(self, table: str, config: SyncConfig) -> AsyncIterator[Dict[str, Any]]:
        query = f"SELECT * FROM {table} ORDER BY createdAt ASC"
        rows = await self._connection.fetch(query)
        for row in rows:
            yield dict(row)

    def get_default_mappings(self) -> Dict[str, List[FieldMapping]]:
        return {
            "qa_records": [
                FieldMapping(source_field="data", target_field="qa_data"),
            ]
        }


class CustomDBSyncAdapter(BaseSyncAdapter):
    """自定义数据库同步适配器"""

    source_type = "database"
    system_type = "custom"
    display_name = "自定义数据库"

    async def connect(self) -> bool:
        self.db_type = self.connection_config.get("db_type", "postgresql")
        if self.db_type == "postgresql":
            self._connection = await asyncpg.connect(
                host=self.connection_config["host"],
                port=self.connection_config.get("port", 5432),
                database=self.connection_config["database"],
                user=self.connection_config["username"],
                password=self.connection_config["password"]
            )
        return True

    async def disconnect(self) -> None:
        if self._connection:
            await self._connection.close()

    async def test_connection(self) -> Dict[str, Any]:
        try:
            await self.connect()
            tables = await self.get_tables()
            await self.disconnect()
            return {"success": True, "tables": tables[:20]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_schema(self) -> List[SchemaInfo]:
        tables = self.connection_config.get("tables", []) or await self.get_tables()
        schemas = []
        for table in tables[:10]:
            try:
                schema = await self._get_table_schema(table)
                count = await self._count_table(table)
                schemas.append(SchemaInfo(table_name=table, columns=schema, row_count=count))
            except:
                pass
        return schemas

    async def _get_table_schema(self, table: str) -> List[Dict[str, Any]]:
        query = "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = $1"
        rows = await self._connection.fetch(query, table)
        return [{"name": r["column_name"], "type": r["data_type"]} for r in rows]

    async def _count_table(self, table: str) -> int:
        return await self._connection.fetchval(f"SELECT COUNT(*) FROM {table}")

    async def get_tables(self) -> List[str]:
        query = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        rows = await self._connection.fetch(query)
        return [r["table_name"] for r in rows]

    async def fetch_data(self, table: str, config: SyncConfig) -> AsyncIterator[Dict[str, Any]]:
        query = f"SELECT * FROM {table} LIMIT {config.batch_size}"
        offset = 0
        while True:
            rows = await self._connection.fetch(f"{query} OFFSET {offset}")
            if not rows:
                break
            for row in rows:
                yield dict(row)
            offset += config.batch_size

    def get_default_mappings(self) -> Dict[str, List[FieldMapping]]:
        return {}


class SyncAdapterFactory:
    """同步适配器工厂"""

    REGISTRY = {
        "dify": DifySyncAdapter,
        "fastgpt": FastGPTSyncAdapter,
        "n8n": N8nSyncAdapter,
        "custom": CustomDBSyncAdapter,
    }

    @staticmethod
    def create(system_type: str, connection_config: Dict[str, Any]) -> BaseSyncAdapter:
        if system_type not in SyncAdapterFactory.REGISTRY:
            raise ValueError(f"不支持的系统类型: {system_type}")
        return SyncAdapterFactory.REGISTRY[system_type](connection_config)

    @staticmethod
    def get_supported_systems() -> List[Dict[str, Any]]:
        return [
            {"system_type": "dify", "display_name": "Dify", "db_type": "postgresql"},
            {"system_type": "fastgpt", "display_name": "FastGPT", "db_type": "mongodb"},
            {"system_type": "n8n", "display_name": "n8n", "db_type": "postgresql"},
            {"system_type": "custom", "display_name": "自定义数据库", "db_type": "any"},
        ]