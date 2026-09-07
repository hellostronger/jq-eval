# 映射调用日志服务 - 将映射调用记录写入 model_request_logs
import logging
import time
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.model import Model
from app.models.model_log import ModelRequestLog
from app.models.model_mapping import ModelMapping

from .protocol_converter import InternalRequest

logger = logging.getLogger(__name__)

RAW_REQUEST_MAX_LEN = 16000  # 原始请求体截断上限，防止超大请求撑爆日志


def truncate(value: Any, max_len: int = RAW_REQUEST_MAX_LEN) -> Any:
    """截断过长的内容"""
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + "...[truncated]"
    return value


def _last_user_text(req: InternalRequest) -> str:
    """取最后一条 user 消息文本（与日志页"提示词"列对齐）"""
    for m in reversed(req.messages):
        if m.role == "user":
            return m.content
    return ""


async def start_log(
    db: AsyncSession,
    mapping: ModelMapping,
    target: Model,
    req: InternalRequest,
    inbound: str,
    outbound: str,
    raw_request: Optional[Dict] = None,
) -> UUID:
    """创建 pending 日志，返回日志ID（调用方需已判断 mapping.log_enabled）"""
    log = ModelRequestLog(
        model_id=target.id,
        mapping_id=mapping.id,
        source="mapping",
        request_type="chat",
        prompt=_last_user_text(req),
        system_prompt=req.system,
        messages=[{"role": m.role, "content": m.content} for m in req.messages],
        params={
            "inbound_protocol": inbound,
            "outbound_protocol": outbound,
            "stream": req.stream,
            "mapping_name": mapping.name,
            "raw_request": truncate(raw_request),
        },
        status="pending",
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return log.id


async def finish_log(
    log_id: Optional[UUID],
    response: Optional[str],
    usage: Optional[Dict[str, Any]] = None,
    finish_reason: Optional[str] = None,
    raw_stop_reason: Optional[str] = None,
    first_token_ms: Optional[int] = None,
    latency_ms: Optional[int] = None,
    error: Optional[str] = None,
    status: str = "success",
    outbound_protocol: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
    mapping_id: Optional[UUID] = None,
):
    """回填日志结果。使用独立 session（流式响应期间请求级 session 的关闭时序不可控）"""
    if log_id is None:
        return

    metadata: Dict[str, Any] = {
        "via_mapping": True,
    }
    if usage is not None:
        metadata["usage"] = usage
        # 统一键名：与 log_recorder 直调链路的 usage_tokens 对齐，便于聚合统计
        metadata["usage_tokens"] = usage
    if finish_reason is not None:
        metadata["finish_reason"] = finish_reason
    if raw_stop_reason is not None:
        metadata["finish_reason_upstream"] = raw_stop_reason
    if first_token_ms is not None:
        metadata["first_token_latency_ms"] = first_token_ms
    if outbound_protocol is not None:
        metadata["outbound_protocol"] = outbound_protocol
    if extra_metadata:
        metadata.update(extra_metadata)

    try:
        async with AsyncSessionLocal() as session:
            result = await session.get(ModelRequestLog, log_id)
            if result:
                result.response = response
                result.response_metadata = metadata
                result.status = status
                result.error_message = error
                result.latency_ms = latency_ms
            if mapping_id:
                mapping_result = await session.get(ModelMapping, mapping_id)
                if mapping_result:
                    from datetime import datetime
                    mapping_result.last_called_at = datetime.utcnow()
            await session.commit()
    except Exception as e:
        logger.warning(f"回填映射调用日志失败 log_id={log_id}: {e}")
