# 方言自适应列类型
#
# 生产库为 PostgreSQL；测试库为 SQLite（内存库，见 tests/conftest.py）。
# SQLAlchemy 的 `dialects.postgresql.UUID/JSONB` 与 `ARRAY` 无法编译为 SQLite DDL，
# 且直连 SQLite 时还会报缺少 `native_uuid`/`JSONB` 适配器。
# 这里的类型在 PostgreSQL 下与原生类型 DDL 等价（UUID / JSONB / 带 dimension 的 ARRAY），
# 在其他方言下降级为 CHAR(32) / JSON / 逗号分隔字符串，保证同一套模型两端可用。
import uuid
from typing import Any, Optional

from sqlalchemy import JSON, String, Text, TypeDecorator
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY


class UUIDType(TypeDecorator):
    """跨方言 UUID 列。PG -> native uuid；其他 -> CHAR(32)（无连字符 hex）。"""

    impl = String
    cache_ok = True

    def __init__(self, as_uuid: bool = False):
        super().__init__(32)
        self._as_uuid = as_uuid

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.UUID(as_uuid=self._as_uuid))
        return dialect.type_descriptor(String(32))

    def process_bind_param(self, value: Any, dialect) -> Optional[Any]:
        if value is None:
            return None
        if isinstance(value, (str, uuid.UUID)):
            value = uuid.UUID(str(value))
        if dialect.name == "postgresql":
            return value if self._as_uuid else str(value)
        return value.hex  # CHAR(32) 存储，无连字符

    def process_result_value(self, value: Any, dialect) -> Optional[Any]:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value if self._as_uuid else str(value)
        value = uuid.UUID(str(value))
        return value if self._as_uuid else str(value)


class JSONType(TypeDecorator):
    """跨方言 JSON 列。PG -> JSONB（与原生 JSONB DDL 等价）；其他 -> JSON。"""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB())
        return dialect.type_descriptor(JSON())


class ArrayType(TypeDecorator):
    """跨方言数组列。PG -> native ARRAY；其他 -> 逗号分隔字符串（读写为 Python list）。

    注意：非 PG 方言下 `col.contains([x])` 降级为子串匹配，语义近似但对
    前缀重叠的值（如 "llm" 与 "llm_x"）可能误匹配；测试数据应使用整词取值。
    """

    impl = Text
    cache_ok = True

    def __init__(self, item_type: Any = String(), dimension: int = 1, **kwargs):
        super().__init__(**kwargs)
        self._item_type = item_type
        self._dimension = dimension

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_ARRAY(self._item_type, self._dimension))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect) -> Optional[Any]:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        return ",".join(str(item) for item in value)

    def process_result_value(self, value: Any, dialect) -> Optional[Any]:
        if value is None:
            return None
        # PG 下 as_tuple=1 时空数组 {} 会以空元组 () 返回；
        # list/tuple 统一转 list，避免 str(()) 生成 ['()'] 这类伪元素
        if isinstance(value, (list, tuple)):
            return list(value)
        return [item for item in str(value).split(",") if item != ""]
