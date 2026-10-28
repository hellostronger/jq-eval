# 大厂 / 通用 profile 的评测适配器
#
# 这些平台没有专用的 query 实现，统一走 api_ingest 的 profile 驱动 ask。
# 好处：入库用的 profile 与评测用的 profile 是同一份，不会出现"上传能通、评测报错"。
from typing import Any, Dict, List, Optional

from app.services.api_ingest.registry import create_connector

from .base import BaseRAGAdapter, RAGResponse


class ProfileAdapter(BaseRAGAdapter):
    """profile 驱动的 RAG 查询适配器"""

    system_type = "generic"
    display_name = "通用 HTTP"
    connector_system_type = "generic"

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.connector = create_connector(self.connector_system_type, config)

    async def query(
        self,
        question: str,
        contexts: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
        **kwargs
    ) -> RAGResponse:
        import time

        start_time = time.time()
        try:
            data = await self.connector.ask(
                question, conversation_id=conversation_id
            )
            return RAGResponse(
                answer=data.get("answer") or "",
                contexts=data.get("contexts") or [],
                retrieval_ids=data.get("retrieval_ids") or [],
                response_time=time.time() - start_time,
                metadata=data.get("metadata") or {},
                success=True,
            )
        except Exception as e:
            return RAGResponse(
                answer="",
                response_time=time.time() - start_time,
                error=self.error_message(e),
                success=False,
            )

    async def health_check(self) -> bool:
        result = await self.connector.check_connection()
        return bool(result.get("healthy"))


class BaiduQianfanAdapter(ProfileAdapter):
    system_type = "baidu_qianfan"
    display_name = "百度千帆 AppBuilder"
    connector_system_type = "baidu_qianfan"


class AliyunBailianAdapter(ProfileAdapter):
    system_type = "aliyun_bailian"
    display_name = "阿里云百炼"
    connector_system_type = "aliyun_bailian"


class TencentHunyuanAdapter(ProfileAdapter):
    system_type = "tencent_hunyuan"
    display_name = "腾讯混元"
    connector_system_type = "tencent_hunyuan"


class TencentYuanqiAdapter(ProfileAdapter):
    system_type = "tencent_yuanqi"
    display_name = "腾讯元器"
    connector_system_type = "tencent_yuanqi"


class VolcengineArkAdapter(ProfileAdapter):
    system_type = "volcengine_ark"
    display_name = "火山引擎方舟"
    connector_system_type = "volcengine_ark"


class XfyunSparkAdapter(ProfileAdapter):
    system_type = "xfyun_spark"
    display_name = "讯飞星火"
    connector_system_type = "xfyun_spark"


class OpenAICompatibleAdapter(ProfileAdapter):
    system_type = "openai_compatible"
    display_name = "OpenAI 兼容 RAG"
    connector_system_type = "openai_compatible"
