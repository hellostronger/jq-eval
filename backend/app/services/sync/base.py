# 数据同步适配器基类
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, AsyncIterator
from pydantic import BaseModel
from datetime import datetime


class SyncConfig(BaseModel):
    """同步配置"""
    batch_size: int = 100
    incremental: bool = False
    since: Optional[datetime] = None
    target_types: List[str] = ["chunks", "qa_records"]


class SyncResult(BaseModel):
    """同步结果"""
    total: int = 0
    synced: int = 0
    failed: int = 0
    errors: List[Dict[str, Any]] = []


class SchemaInfo(BaseModel):
    """Schema信息"""
    table_name: str
    columns: List[Dict[str, Any]] = []
    row_count: Optional[int] = None


class FieldMapping(BaseModel):
    """字段映射"""
    source_field: str
    target_field: str
    transform: Optional[str] = None


class BaseSyncAdapter(ABC):
    """数据同步适配器基类"""

    source_type: str
    system_type: str
    display_name: str

    def __init__(self, connection_config: Dict[str, Any]):
        self.connection_config = connection_config
        self._connection = None

    @abstractmethod
    async def connect(self) -> bool:
        """建立连接"""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        pass

    @abstractmethod
    async def test_connection(self) -> Dict[str, Any]:
        """测试连接"""
        pass

    @abstractmethod
    async def get_schema(self) -> List[SchemaInfo]:
        """获取数据库Schema"""
        pass

    @abstractmethod
    async def get_tables(self) -> List[str]:
        """获取可用表/集合列表"""
        pass

    @abstractmethod
    async def fetch_data(
        self,
        table: str,
        config: SyncConfig
    ) -> AsyncIterator[Dict[str, Any]]:
        """获取数据"""
        pass

    @abstractmethod
    def get_default_mappings(self) -> Dict[str, List[FieldMapping]]:
        """获取默认字段映射"""
        pass

    def transform_data(
        self,
        raw_data: Dict[str, Any],
        mapping: List[FieldMapping],
        target_type: str
    ) -> Dict[str, Any]:
        """数据转换"""
        result = {}
        for m in mapping:
            value = raw_data.get(m.source_field)
            if m.transform:
                value = self._apply_transform(value, m.transform)
            result[m.target_field] = value
        return result

    def _apply_transform(self, value: Any, transform: str) -> Any:
        """应用转换函数"""
        transforms = {
            "to_string": lambda v: str(v) if v else None,
            "to_int": lambda v: int(v) if v else 0,
            "to_float": lambda v: float(v) if v else 0.0,
            "to_datetime": lambda v: datetime.fromisoformat(v) if v else None,
            "json_to_list": lambda v: list(v.values()) if isinstance(v, dict) else v,
        }
        if transform in transforms:
            return transforms[transform](value)
        return value