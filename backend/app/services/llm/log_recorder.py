# 日志记录服务
import time
import logging
from typing import Dict, Any, Optional, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.model import Model
from app.models.model_log import ModelRequestLog

logger = logging.getLogger(__name__)


class LogRecorder:
    """模型请求响应日志记录器"""

    def __init__(self, db: AsyncSession, model_id: UUID, session_id: Optional[UUID] = None):
        """
        Args:
            db: 数据库会话
            model_id: 模型ID
            session_id: 会话ID（可选）
        """
        self.db = db
        self.model_id = model_id
        self.session_id = session_id
        self._enabled = False
        # 异步环境下不能在构造函数里同步查库（run_until_complete 在运行中的
        # 事件循环里会抛 RuntimeError），统一由 create_log_recorder / check_and_enable 异步初始化

    def _check_enabled(self):
        """兼容旧调用：仅返回当前缓存状态，不做 IO"""
        return self._enabled

    async def _async_check_enabled(self) -> bool:
        """异步检查模型是否启用了日志保存"""
        result = await self.db.execute(
            select(Model.save_logs).where(Model.id == self.model_id)
        )
        row = result.scalar_one_or_none()
        return row if row is not None else False

    async def check_and_enable(self) -> bool:
        """异步检查并启用日志记录"""
        self._enabled = await self._async_check_enabled()
        return self._enabled

    def is_enabled(self) -> bool:
        """检查是否启用"""
        return self._enabled

    async def record_request(
        self,
        request_type: str,
        prompt: str,
        system_prompt: Optional[str] = None,
        messages: Optional[List[Dict]] = None,
        params: Optional[Dict] = None,
    ) -> Optional[UUID]:
        """
        记录请求信息，返回日志ID

        Args:
            request_type: 请求类型 (chat/embedding/rerank)
            prompt: 用户输入/请求内容
            system_prompt: 系统提示（LLM）
            messages: 完整消息列表（多轮对话）
            params: 请求参数

        Returns:
            日志ID，如果未启用则返回 None
        """
        if not self._enabled:
            return None

        log = ModelRequestLog(
            model_id=self.model_id,
            session_id=self.session_id,
            request_type=request_type,
            prompt=prompt,
            system_prompt=system_prompt,
            messages=messages,
            params=params,
            status="pending",
        )
        self.db.add(log)
        await self.db.flush()
        await self.db.refresh(log)
        return log.id

    async def record_response(
        self,
        log_id: UUID,
        response: str,
        metadata: Optional[Dict] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        latency_ms: Optional[int] = None,
    ):
        """
        记录响应信息

        Args:
            log_id: 日志ID
            response: 模型响应内容
            metadata: 响应元数据
            status: 状态
            error_message: 错误信息
            latency_ms: 响应耗时
        """
        if not self._enabled or log_id is None:
            return

        result = await self.db.execute(
            select(ModelRequestLog).where(ModelRequestLog.id == log_id)
        )
        log = result.scalar_one_or_none()
        if log:
            log.response = response
            log.response_metadata = metadata
            log.status = status
            log.error_message = error_message
            log.latency_ms = latency_ms

    async def record_replay(
        self,
        source_log_id: UUID,
        replay_model_id: UUID,
        response: str,
        metadata: Optional[Dict] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        latency_ms: Optional[int] = None,
    ):
        """
        记录回放测试结果

        Args:
            source_log_id: 源日志ID
            replay_model_id: 回放使用的模型ID
            response: 回放响应
            metadata: 响应元数据
            status: 状态
            error_message: 错误信息
            latency_ms: 响应耗时
        """
        # 获取源日志
        result = await self.db.execute(
            select(ModelRequestLog).where(ModelRequestLog.id == source_log_id)
        )
        source_log = result.scalar_one_or_none()
        if not source_log:
            logger.warning(f"源日志 {source_log_id} 不存在")
            return

        # 创建回放日志
        replay_log = ModelRequestLog(
            model_id=replay_model_id,
            session_id=source_log.session_id,
            request_type=source_log.request_type,
            prompt=source_log.prompt,
            system_prompt=source_log.system_prompt,
            messages=source_log.messages,
            params=source_log.params,
            response=response,
            response_metadata=metadata,
            status=status,
            error_message=error_message,
            latency_ms=latency_ms,
            is_replay=True,
            replay_from_log_id=source_log_id,
            replay_model_id=replay_model_id,
        )
        self.db.add(replay_log)


async def create_log_recorder(
    db: AsyncSession,
    model_id: UUID,
    session_id: Optional[UUID] = None,
) -> LogRecorder:
    """创建日志记录器并检查是否启用"""
    recorder = LogRecorder(db, model_id, session_id)
    await recorder.check_and_enable()
    return recorder


def extract_usage_tokens(response: Any) -> Optional[Dict[str, int]]:
    """从 LangChain 响应中提取 token 用量，统一为 openai 键名。

    优先 langchain 标准的 usage_metadata，兜底 response_metadata /
    additional_kwargs 中的 openai 风格 token_usage。
    """
    usage_metadata = getattr(response, "usage_metadata", None)
    if isinstance(usage_metadata, dict):
        prompt = usage_metadata.get("input_tokens") or 0
        completion = usage_metadata.get("output_tokens") or 0
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": usage_metadata.get("total_tokens") or (prompt + completion),
        }

    raw_meta = getattr(response, "response_metadata", None) or {}
    raw_usage = raw_meta.get("token_usage") or raw_meta.get("usage") \
        or (getattr(response, "additional_kwargs", None) or {}).get("token_usage")
    if isinstance(raw_usage, dict) and (raw_usage.get("prompt_tokens") or raw_usage.get("completion_tokens")):
        prompt = raw_usage.get("prompt_tokens") or 0
        completion = raw_usage.get("completion_tokens") or 0
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": raw_usage.get("total_tokens") or (prompt + completion),
        }
    return None


class LLMCallLogger:
    """LLM调用日志包装器，用于包装LangChain调用"""

    def __init__(
        self,
        llm,
        recorder: Optional[LogRecorder],
        request_type: str = "chat",
    ):
        """
        Args:
            llm: LangChain LLM实例
            recorder: 日志记录器（可选）
            request_type: 请求类型
        """
        self.llm = llm
        self.recorder = recorder
        self.request_type = request_type

    async def generate(self, prompt: str, **kwargs):
        """兼容简化调用约定：await llm.generate(prompt) 返回文本。

        LangChain 的 generate(messages) 是同步且要求消息列表，这里统一转 ainvoke，
        并返回纯文本内容，方便指标/评估代码直接使用。
        """
        response = await self.ainvoke(prompt, **kwargs)
        if hasattr(response, "content"):
            return response.content
        return str(response)

    async def ainvoke(self, messages, **kwargs):
        """异步调用并记录日志（messages 支持纯字符串或 LangChain 消息列表）"""
        if not self.recorder or not self.recorder.is_enabled():
            return await self.llm.ainvoke(messages, **kwargs)

        # 提取请求信息
        prompt = ""
        system_prompt = None
        messages_data = []

        if isinstance(messages, str):
            prompt = messages
            messages_data = [{"role": "user", "content": messages}]
        else:
            for msg in messages:
                msg_dict = {
                    "role": msg.type if hasattr(msg, "type") else "unknown",
                    "content": msg.content if hasattr(msg, "content") else str(msg),
                }
                messages_data.append(msg_dict)
                if msg.type == "system":
                    system_prompt = msg.content
                elif msg.type == "human":
                    prompt = msg.content

        params = {
            "temperature": getattr(self.llm, "temperature", None),
            "max_tokens": getattr(self.llm, "max_tokens", None),
        }

        # 记录请求
        log_id = await self.recorder.record_request(
            request_type=self.request_type,
            prompt=prompt,
            system_prompt=system_prompt,
            messages=messages_data,
            params=params,
        )

        # 调用LLM
        start_time = time.time()
        try:
            response = await self.llm.ainvoke(messages, **kwargs)
            latency_ms = int((time.time() - start_time) * 1000)

            # 提取响应
            response_content = response.content if hasattr(response, "content") else str(response)
            metadata: Dict[str, Any] = {
                "response_type": type(response).__name__,
            }

            # 提取 token 用量
            usage = extract_usage_tokens(response)
            if usage:
                metadata["usage_tokens"] = usage

            # 记录响应
            await self.recorder.record_response(
                log_id=log_id,
                response=response_content,
                metadata=metadata,
                status="success",
                latency_ms=latency_ms,
            )

            return response
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            await self.recorder.record_response(
                log_id=log_id,
                response=None,
                metadata=None,
                status="failed",
                error_message=str(e),
                latency_ms=latency_ms,
            )
            raise