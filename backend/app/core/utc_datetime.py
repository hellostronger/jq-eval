# 带 UTC 时区的 datetime 类型
# 数据库存 naive UTC；Pydantic 序列化 naive datetime 时输出无时区后缀，
# 前端 new Date() 会按本地时间解析导致差 8 小时。
# 本模块的 UTCDatetime 在校验阶段把 naive datetime 附加 UTC 时区，
# 序列化输出 ISO8601 带时区格式（如 2026-09-05T07:48:07Z），前端可正确换算。
from datetime import datetime, timezone
from typing import Annotated

from pydantic import BeforeValidator


def _attach_utc(value):
    """naive datetime 视为 UTC 补 tzinfo（aware/None 原样返回）"""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


UTCDatetime = Annotated[datetime, BeforeValidator(_attach_utc)]
