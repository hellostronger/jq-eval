# 开源 RAG / 知识库方案覆盖清单（>1k GitHub stars）
#
# 为什么单独维护一份清单：
# 「支持哪些系统」不能只靠注册表反推——注册表里有的只是已经接了 API 的；
# 而用户真正会问的是「GitHub 上过千星的开源方案，你们覆盖了哪些、没覆盖为什么」。
# 这里把候选、star 快照、仓库是否归档、接入方式和原因放在一处，
# 由 registry / 前端 / 文档共同读取，避免三处口径不一致。
#
# 纳入规则（2026-10-28 快照）：
# 1) 面向最终用户的 RAG / 知识库应用，且提供可调用的 HTTP API（自建或官方云）；
# 2) 纯框架/库（LangChain、LlamaIndex、Haystack、GraphRAG、RAG-Anything、MiniRAG）、
#    向量数据库（Milvus/Qdrant/Weaviate/Chroma）、解析器（Docling/MinerU）、
#    评测库（Ragas/DeepEval）、记忆层（Mem0/Cognee/Zep/Letta）不计入；
#    它们通过 SDK / 自建网关间接参与评测，而不是作为一个「被测 RAG 系统」。
# 3) 纯聊天 UI（LibreChat/LobeChat）如果没有稳定的知识库管理 API，也不计入；
# 4) 已归档仓库仍然列出：能跑就接，不能跑就写明原因，不能静默消失。
#
# star 数是 2026-10-28 通过 GitHub API 取的快照，会随时间变化，不要当成实时值。
from typing import Any, Dict, List, Optional

STAR_SNAPSHOT = "2026-10-28"


def _entry(
    name: str,
    repo: str,
    stars: int,
    *,
    system_type: Optional[str] = None,
    category: str = "rag_system",
    integration: str = "excluded",
    coverage: str = "none",
    archived: bool = False,
    last_push: str = "",
    docs_url: str = "",
    notes: str = "",
) -> Dict[str, Any]:
    return {
        "name": name,
        "repo": repo,
        "stars": stars,
        "system_type": system_type,
        "category": category,
        "integration": integration,
        "coverage": coverage,
        "archived": archived,
        "last_push": last_push,
        "docs_url": docs_url,
        "notes": notes,
    }


CATALOG: List[Dict[str, Any]] = [
    # ------------------------------------------------------------ 全链路原生
    _entry(
        "Dify", "https://github.com/langgenius/dify", 159824,
        system_type="dify", integration="native", coverage="full",
        last_push="2026-10-28", docs_url="https://docs.dify.ai/",
        notes="知识库 API + 应用 API；本地已实测（见 docs/api-ingest.md）。",
    ),
    _entry(
        "Open WebUI", "https://github.com/open-webui/open-webui", 157054,
        system_type="open_webui", integration="native", coverage="partial",
        last_push="2026-10-28", docs_url="https://docs.openwebui.com/",
        notes="知识库 = knowledge collection；上传后加入知识库即完成向量化。无分片枚举接口。",
    ),
    _entry(
        "RAGFlow", "https://github.com/infiniflow/ragflow", 93019,
        system_type="ragflow", integration="native", coverage="full",
        last_push="2026-10-28", docs_url="https://ragflow.io/docs/dev/http_api_reference",
        notes="v1.0.0-rc2 本地实测；含建库/上传/解析/分片/问答。",
    ),
    _entry(
        "AnythingLLM", "https://github.com/Mintplex-Labs/anything-llm", 67682,
        system_type="anythingllm", integration="native", coverage="partial",
        last_push="2026-10-28", docs_url="https://docs.anythingllm.com/",
        notes="workspace = 知识库；上传可带 addToWorkspaces 直接入库。无分片枚举，只有 vector-search TopN。",
    ),
    _entry(
        "PrivateGPT", "https://github.com/zylon-ai/private-gpt", 57615,
        system_type="privategpt", integration="native", coverage="partial",
        last_push="2026-10-27", docs_url="https://docs.privategpt.dev/",
        notes="无知识库概念，按账号级文档接入；问答为 OpenAI 兼容 /v1/chat/completions。",
    ),
    _entry(
        "Flowise", "https://github.com/FlowiseAI/Flowise", 55532,
        system_type="flowise", integration="profile", coverage="ask_only",
        archived=True, last_push="2026-08-13", docs_url="https://docs.flowiseai.com/",
        notes="仓库已归档；知识库走 Document Store，接口随版本漂移，默认只接 prediction 问答，需 chatflow_id。",
    ),
    _entry(
        "LightRAG", "https://github.com/HKUDS/LightRAG", 40392,
        system_type="lightrag", integration="native", coverage="full",
        last_push="2026-10-27", docs_url="https://github.com/HKUDS/LightRAG",
        notes="lightrag-server：/documents 上传与状态、/query 检索、/chunks 分片；图索引与向量索引混合检索。",
    ),
    _entry(
        "Quivr", "https://github.com/The-Vibe-Company/quivr", 39611,
        system_type="quivr", integration="gateway", coverage="none",
        last_push="2026-10-28", docs_url="https://github.com/The-Vibe-Company/quivr",
        notes="仓库已从 QuivrHQ 迁到 The-Vibe-Company 并转向内容流引擎，旧的 RAG API 契约不再稳定；建议经自建网关接入。",
    ),
    _entry(
        "PageIndex", "https://github.com/VectifyAI/PageIndex", 39874,
        system_type="pageindex", integration="native", coverage="partial",
        last_push="2026-10-28", docs_url="https://docs.pageindex.ai/",
        notes="无向量树索引；云端 API 已接，上传即自动建树，树节点作为分片。",
    ),
    _entry(
        "Langchain-Chatchat", "https://github.com/chatchat-space/Langchain-Chatchat", 38715,
        system_type="langchain_chatchat", integration="native", coverage="partial",
        last_push="2025-11-10", docs_url="https://github.com/chatchat-space/Langchain-Chatchat",
        notes="知识与对话 API 都齐全；上传后同步建向量库。无分片枚举接口。",
    ),
    _entry(
        "Khoj", "https://github.com/khoj-ai/khoj", 37873,
        system_type="khoj", integration="native", coverage="partial",
        last_push="2026-08-02", docs_url="https://docs.khoj.dev/",
        notes="按账号级文档接入；/api/content 上传、/api/chat 问答，默认非流式取 references。",
    ),
    _entry(
        "Onyx（原 Danswer）", "https://github.com/onyx-dot-app/onyx", 33053,
        system_type="onyx", integration="gateway", coverage="ask_only",
        last_push="2026-10-28", docs_url="https://docs.onyx.app/",
        notes="连接器管理需管理员权限且问答默认流式；建议先用 Onyx 建好知识库，再用通用 profile 调 /api/chat/send-message。",
    ),
    _entry(
        "FastGPT", "https://github.com/labring/FastGPT", 29932,
        system_type="fastgpt", integration="native", coverage="full",
        last_push="2026-10-28", docs_url="https://doc.fastgpt.io/",
        notes="数据集 + 应用 API；已按文档实现，未本地实测。",
    ),
    _entry(
        "kotaemon", "https://github.com/Cinnamon/kotaemon", 25834,
        category="rag_system", integration="excluded",
        last_push="2026-07-14", docs_url="https://github.com/Cinnamon/kotaemon",
        notes="以 Gradio UI / 本地库为主，没有稳定的公共 HTTP 知识库契约；不纳入 API 接入。",
    ),
    _entry(
        "RAG-Anything", "https://github.com/HKUDS/RAG-Anything", 24250,
        category="framework", integration="excluded",
        last_push="2026-10-28", docs_url="https://github.com/HKUDS/RAG-Anything",
        notes="基于 LightRAG 的多模态 RAG 框架/库，不是可独立部署的知识库服务；用其 SDK 包一层网关后再接。",
    ),
    _entry(
        "MaxKB", "https://github.com/1Panel-dev/MaxKB", 23063,
        system_type="maxkb", integration="native", coverage="full",
        last_push="2026-10-28", docs_url="https://docs.fit2cloud.com/maxkb/",
        notes="dataset API + application chat API；知识库 Key 与应用 Key 分开填写。",
    ),
    _entry(
        "LLM Wiki", "https://github.com/nashsu/llm_wiki", 21092,
        system_type="llm_wiki", integration="native", coverage="partial",
        last_push="2026-10-28", docs_url="https://github.com/nashsu/llm_wiki",
        notes="本地桌面版 API；只能写 Markdown/wiki 页并 embed，不支持原始文件上传与分片枚举。",
    ),
    _entry(
        "DB-GPT", "https://github.com/eosphoros-ai/DB-GPT", 20210,
        system_type="dbgpt", integration="profile", coverage="ask_only",
        last_push="2026-10-28", docs_url="https://docs.dbgpt.cn/",
        notes="提供 OpenAI 兼容 /api/v1/chat/completions；知识库/数据源在 DB-GPT 内配置，默认只接问答。",
    ),
    _entry(
        "DocsGPT", "https://github.com/arc53/DocsGPT", 18339,
        system_type="docsgpt", integration="native", coverage="partial",
        last_push="2026-10-28", docs_url="https://docs.docsgpt.cloud/",
        notes="/api/upload 上传、/api/chat 问答；无独立知识库 ID，按账号级文档接入。",
    ),
    _entry(
        "QAnything", "https://github.com/netease-youdao/QAnything", 14207,
        system_type="qanything", integration="native", coverage="partial",
        last_push="2026-10-28", docs_url="https://github.com/netease-youdao/QAnything",
        notes="本地 API：create_kb / upload_files / chat；user_id + kb_id 隔离，无分片枚举。",
    ),
    _entry(
        "BISHENG", "https://github.com/dataelement/bisheng", 12089,
        system_type="bisheng", integration="gateway", coverage="ask_only",
        last_push="2026-10-28", docs_url="https://docs.bisheng.ai/",
        notes="知识库与工作流接口按版本差异较大，且强依赖应用/工作流 ID；建议先在工作流里封装问答，再用通用 profile 接入。",
    ),
    _entry(
        "R2R", "https://github.com/SciPhi-AI/R2R", 8047,
        system_type="r2r", integration="native", coverage="full",
        last_push="2025-11-07", docs_url="https://r2r-docs.sciphi.ai/",
        notes="v3 documents/retrieval/chat；仓库近一年未更新，按 v3 契约实现并标未实测。",
    ),
    _entry(
        "Verba", "https://github.com/weaviate/Verba", 7691,
        integration="excluded", archived=True,
        last_push="2026-06-08", docs_url="https://github.com/weaviate/Verba",
        notes="已归档；Streamlit 应用直接连 Weaviate，没有稳定的公共 HTTP 知识库 API。",
    ),
    _entry(
        "Cognita", "https://github.com/truefoundry/cognita", 4409,
        integration="excluded", archived=True,
        last_push="2026-03-13", docs_url="https://github.com/truefoundry/cognita",
        notes="已归档的 RAG 框架；API 不稳定且无维护，不建议作为被测系统。",
    ),
    _entry(
        "MiniRAG", "https://github.com/HKUDS/MiniRAG", 2024,
        category="framework", integration="excluded",
        last_push="2025-10-16", docs_url="https://github.com/HKUDS/MiniRAG",
        notes="研究型 RAG 框架/库，没有独立服务端；用 SDK 包网关后再接。",
    ),

    # ------------------------------------------------- 相邻但不能算被测 RAG 的
    _entry(
        "Langflow", "https://github.com/langflow-ai/langflow", 156106,
        system_type="langflow", integration="profile", coverage="ask_only",
        last_push="2026-10-28", docs_url="https://docs.langflow.org/",
        notes="可视化编排平台，不是知识库；已提供 /api/v1/run/{flow_id} 的问答 profile，RAG 逻辑在 flow 内。",
    ),
    _entry(
        "Mem0", "https://github.com/mem0ai/mem0", 67998,
        category="memory", integration="excluded",
        last_push="2026-10-26", docs_url="https://docs.mem0.ai/",
        notes="记忆层，不是 RAG 知识库；不纳入被测系统。",
    ),
    _entry(
        "Cognee", "https://github.com/topoteretes/cognee", 32862,
        category="memory", integration="excluded",
        last_push="2026-10-28", docs_url="https://docs.cognee.ai/",
        notes="记忆/图谱框架；如需评测，先封装成 HTTP 网关。",
    ),
    _entry(
        "Letta（原 MemGPT）", "https://github.com/letta-ai/letta", 25273,
        category="memory", integration="excluded",
        last_push="2026-10-18", docs_url="https://docs.letta.com/",
        notes="有状态智能体/记忆框架，不是 RAG 知识库服务。",
    ),
    _entry(
        "txtai", "https://github.com/neuml/txtai", 13043,
        category="framework", integration="excluded",
        last_push="2026-10-27", docs_url="https://neuml.github.io/txtai/",
        notes="嵌入式向量库/RAG 库，不是独立知识库服务。",
    ),
    _entry(
        "Zep", "https://github.com/getzep/zep", 4975,
        category="memory", integration="excluded",
        last_push="2026-10-20", docs_url="https://help.getzep.com/",
        notes="记忆层，不是 RAG 知识库；不纳入被测系统。",
    ),
]


def get_entry(system_type: str) -> Optional[Dict[str, Any]]:
    for item in CATALOG:
        if item.get("system_type") == system_type:
            return item
    return None


def catalog_as_list() -> List[Dict[str, Any]]:
    return [dict(item) for item in CATALOG]


def coverage_summary() -> Dict[str, Any]:
    """给文档/健康检查用的口径：多少纳入、多少是网关、多少明确排除"""
    counts = {"native": 0, "profile": 0, "gateway": 0, "excluded": 0}
    for item in CATALOG:
        counts[item["integration"]] = counts.get(item["integration"], 0) + 1
    return {
        "star_snapshot": STAR_SNAPSHOT,
        "total": len(CATALOG),
        "integration": counts,
        "covered": counts["native"] + counts["profile"],
    }
