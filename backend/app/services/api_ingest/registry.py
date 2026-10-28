# API 接入连接器注册表
from typing import Any, Dict, List, Optional

import httpx

from .base import BaseApiIngestConnector, IngestCapabilities
from .coze import CozeConnector
from .dify import DifyConnector
from .fastgpt import FastGPTConnector
from .generic import GenericHttpConnector
from .llm_wiki import LlmWikiConnector
from .pageindex import PageIndexConnector
from .profiles import PROFILES
from .ragflow import RAGFlowConnector

# 原生全链路连接器（有专用实现）
NATIVE_CONNECTORS = {
    "ragflow": RAGFlowConnector,
    "dify": DifyConnector,
    "fastgpt": FastGPTConnector,
    "coze": CozeConnector,
    # 开源新形态：树索引（无向量）与 LLM Wiki 模式
    "pageindex": PageIndexConnector,
    "llm_wiki": LlmWikiConnector,
}

# 通用 profile 驱动的系统类型（大厂 / 自研网关）
GENERIC_TYPES = list(PROFILES.keys()) + ["generic"]


def create_connector(
    system_type: str,
    config: Dict[str, Any],
    *,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> BaseApiIngestConnector:
    """按 system_type 创建连接器

    transport 仅供测试注入（httpx.MockTransport），生产传 None。
    """
    if system_type in NATIVE_CONNECTORS:
        return NATIVE_CONNECTORS[system_type](config, transport=transport)

    if system_type in PROFILES:
        preset = PROFILES[system_type]
        connector = GenericHttpConnector(
            config,
            profile=preset["profile"],
            transport=transport,
        )
        connector.system_type = system_type
        connector.display_name = preset["display_name"]
        connector.api_doc_url = preset.get("api_doc_url") or ""
        connector.capabilities.docs_url = connector.api_doc_url
        connector.capabilities.notes = preset.get("notes") or connector.capabilities.notes
        return connector

    if system_type in ("generic", "custom"):
        connector = GenericHttpConnector(config, transport=transport)
        connector.system_type = system_type
        return connector

    raise ValueError(f"不支持 API 接入的系统类型: {system_type}")


def supports_api_ingest(system_type: str) -> bool:
    return system_type in NATIVE_CONNECTORS or system_type in GENERIC_TYPES


def list_connector_types() -> List[Dict[str, Any]]:
    """给前端的能力清单（含未实测标记，避免把"按文档实现"说成"已验证"）"""
    items: List[Dict[str, Any]] = []

    for system_type, connector_cls in NATIVE_CONNECTORS.items():
        caps: IngestCapabilities = connector_cls.capabilities
        items.append(
            {
                "system_type": system_type,
                "display_name": connector_cls.display_name,
                "api_doc_url": connector_cls.api_doc_url,
                "default_endpoint": "",
                "capabilities": caps.as_dict(),
            }
        )

    for system_type, preset in PROFILES.items():
        profile = preset.get("profile") or {}
        caps = IngestCapabilities(
            list_knowledge_bases="list_kb" in profile,
            create_knowledge_base="create_kb" in profile,
            upload_documents="upload" in profile,
            parse_documents="parse" in profile,
            list_chunks="list_chunks" in profile,
            create_chat=False,
            ask="ask" in profile,
            verified=bool(preset.get("verified")),
            docs_url=preset.get("api_doc_url") or "",
            notes=preset.get("notes") or "",
        )
        items.append(
            {
                "system_type": system_type,
                "display_name": preset["display_name"],
                "api_doc_url": preset.get("api_doc_url") or "",
                "default_endpoint": preset.get("api_endpoint") or "",
                "capabilities": caps.as_dict(),
            }
        )

    items.append(
        {
            "system_type": "generic",
            "display_name": "通用 HTTP（自定义 profile）",
            "api_doc_url": "",
            "default_endpoint": "",
            "capabilities": IngestCapabilities(
                list_knowledge_bases=False,
                create_knowledge_base=False,
                upload_documents=False,
                parse_documents=False,
                list_chunks=False,
                create_chat=False,
                ask=True,
                docs_url="",
                notes="由连接配置中的 ingest_profile 决定能力；参考 backend/app/services/api_ingest/generic.py 注释。",
            ).as_dict(),
        }
    )
    return items
