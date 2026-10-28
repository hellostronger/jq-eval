# API 全链路入库连接器的离线契约测试
#
# 这些测试不连真实系统：用 httpx.MockTransport 扮演 RAGFlow / Dify / FastGPT / Coze，
# 锁住「请求形状 + 响应解析」这两个最容易随上游版本漂移的部分。
# 真实部署的联调验证放在 tests/manual 之外，用 scripts 或 curl 记录，避免 CI 依赖外部服务。
import json

import httpx
import pytest

from app.services.api_ingest import create_connector, list_connector_types, supports_api_ingest
from app.services.api_ingest.base import ConnectorError, dig


def routes_transport(routes, calls=None):
    """按 (method, path) 分派响应；value 可以是 dict 也可以是 callable(request)"""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        key = (request.method.upper(), request.url.path)
        route = routes.get(key)
        if route is None:
            return httpx.Response(404, json={"detail": f"unmocked {request.method} {request.url.path}"})
        if callable(route):
            return route(request)
        return httpx.Response(200, json=route)

    return httpx.MockTransport(handler)


# --------------------------------------------------------------------- 基础


def test_dig_supports_dict_list_and_negative_index():
    payload = {"data": {"docs": [{"name": "a"}, {"name": "b"}], "last": [1, 2, 3]}}
    assert dig(payload, "data.docs.1.name") == "b"
    assert dig(payload, "data.last.-1") == 3
    assert dig(payload, "data.missing.name", "fallback") == "fallback"


def test_registry_lists_native_and_cloud_types():
    types = {item["system_type"]: item for item in list_connector_types()}
    for system_type in ("ragflow", "dify", "fastgpt", "coze"):
        assert types[system_type]["capabilities"]["upload_documents"] is True
        # 本地部署过之前不要谎称已验证
        assert types[system_type]["capabilities"]["verified"] is False

    # 云端是按文档实现的预设，必须显式标记未实测
    for system_type in ("baidu_qianfan", "aliyun_bailian", "volcengine_ark", "xfyun_spark"):
        assert system_type in types
        assert types[system_type]["capabilities"]["verified"] is False
        assert types[system_type]["api_doc_url"]

    assert supports_api_ingest("ragflow")
    assert supports_api_ingest("generic")
    assert not supports_api_ingest("unknown_system")


def test_registry_unknown_system_raises():
    with pytest.raises(ValueError):
        create_connector("not-a-rag-system", {})


def test_generic_profile_capabilities_follow_profile():
    connector = create_connector(
        "generic",
        {
            "api_endpoint": "http://gw.local",
            "ingest_profile": {
                "list_kb": {"path": "/kbs", "items_path": "data"},
                "ask": {"path": "/ask", "answer_path": "answer"},
            },
        },
    )
    assert connector.capabilities.list_knowledge_bases is True
    assert connector.capabilities.upload_documents is False
    assert connector.capabilities.ask is True


# ------------------------------------------------------------------ RAGFlow


def test_ragflow_full_ingest_flow():
    calls = []
    poll_state = {"count": 0}

    def documents_route(request: httpx.Request) -> httpx.Response:
        poll_state["count"] += 1
        run = "RUNNING" if poll_state["count"] < 3 else "DONE"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "docs": [
                        {"id": "doc1", "name": "faq.md", "run": run, "progress": 0.4},
                        {"id": "doc-other", "name": "other.md", "run": "DONE"},
                    ]
                },
            },
        )

    routes = {
        ("GET", "/api/v1/datasets"): {
            "code": 0,
            "data": [{"id": "kb1", "name": "已有库"}],
        },
        ("POST", "/api/v1/datasets"): {
            "code": 0,
            "data": {"id": "kb-new", "name": "新建库"},
        },
        ("POST", "/api/v1/datasets/kb-new/documents"): {
            "code": 0,
            "data": [{"id": "doc1", "name": "faq.md"}],
        },
        ("POST", "/api/v1/documents/ingest"): {"code": 0, "data": True},
        ("GET", "/api/v1/datasets/kb-new/documents"): documents_route,
        ("GET", "/api/v1/datasets/kb-new/documents/doc1/chunks"): {
            "code": 0,
            "data": {
                "total": 2,
                "chunks": [
                    {"id": "c1", "content": "退款政策是七天无理由", "document_id": "doc1"},
                    {"id": "c2", "content": "发票在订单页申请", "document_id": "doc1"},
                ],
            },
        },
        ("POST", "/api/v1/chats"): {"code": 0, "data": {"id": "chat1"}},
        ("POST", "/api/v1/chat/completions"): {
            "code": 0,
            "data": {
                "answer": "七天无理由",
                "reference": {"chunks": [{"id": "c1", "content": "退款政策是七天无理由"}]},
            },
        },
    }
    connector = create_connector(
        "ragflow",
        {"api_endpoint": "http://ragflow.local:9380"},
        transport=routes_transport(routes, calls),
    )

    assert connector.api_root == "http://ragflow.local:9380/api/v1"

    kbs = asyncio_run(connector.list_knowledge_bases())
    assert [(kb.id, kb.name) for kb in kbs] == [("kb1", "已有库")]

    created = asyncio_run(connector.create_knowledge_base("新建库", embedding_model="BAAI/bge-m3"))
    create_request = next(r for r in calls if r.method == "POST" and r.url.path == "/api/v1/datasets")
    create_body = json.loads(create_request.content)
    # v1.0：parse_type 是整数 1（BuiltIn），且不能带 description
    assert create_body["parse_type"] == 1
    assert create_body["parser_id"] == "naive"
    assert create_body["embedding_model"] == "BAAI/bge-m3"
    assert "description" not in create_body
    assert "chunk_method" not in create_body
    assert created.id == "kb-new"

    uploaded = asyncio_run(
        connector.upload_document("kb-new", "faq.md", "退款政策".encode("utf-8"), "text/markdown")
    )
    upload_request = next(r for r in calls if r.url.path.endswith("/datasets/kb-new/documents"))
    assert "multipart/form-data" in upload_request.headers["content-type"]
    assert "退款政策".encode("utf-8") in upload_request.content
    assert uploaded.id == "doc1"

    asyncio_run(connector.trigger_parse("kb-new", ["doc1"]))
    parse_request = next(r for r in calls if r.url.path == "/api/v1/documents/ingest")
    # run 是 TaskStatus 枚举的字符串形式（"1"=Running）；传 "RUNNING" 会被静默忽略
    assert json.loads(parse_request.content) == {"doc_ids": ["doc1"], "run": "1"}

    progress_snapshots = []
    ready = asyncio_run(
        connector.wait_documents_ready(
            "kb-new",
            ["doc1"],
            timeout=2,
            interval=0.001,
            on_progress=lambda done, total, docs: progress_snapshots.append((done, total)),
        )
    )
    assert len(ready) == 1 and ready[0].ready
    assert poll_state["count"] >= 3
    assert progress_snapshots[-1] == (1, 1)

    chunks = asyncio_run(connector.list_chunks("kb-new", "doc1"))
    assert [chunk.content for chunk in chunks] == ["退款政策是七天无理由", "发票在订单页申请"]

    chat_id = asyncio_run(connector.ensure_chat("评测会话", ["kb-new"]))
    assert chat_id == "chat1"

    answer = asyncio_run(connector.ask("怎么退款?", chat_id="chat1"))
    assert answer["answer"] == "七天无理由"
    assert answer["contexts"] == ["退款政策是七天无理由"]
    assert answer["retrieval_ids"] == ["c1"]


def test_ragflow_envelope_error_is_not_treated_as_success():
    connector = create_connector(
        "ragflow",
        {"api_endpoint": "http://ragflow.local:9380"},
        transport=routes_transport(
            {
                ("GET", "/api/v1/datasets"): {
                    "code": 102,
                    "message": "User authentication failed",
                }
            }
        ),
    )
    with pytest.raises(ConnectorError) as exc_info:
        asyncio_run(connector.list_knowledge_bases())
    assert "code=102" in str(exc_info.value)
    assert "authentication" in str(exc_info.value)


def test_ragflow_document_status_mapping():
    connector = create_connector("ragflow", {"api_endpoint": "http://ragflow.local"})
    # 0.x 的 run 字段
    assert connector._map_document({"id": "1", "run": "DONE"}).status == "done"
    assert connector._map_document({"id": "1", "run": "FAIL", "progress_msg": "boom"}).failed
    assert connector._map_document({"id": "1", "run": "RUNNING", "progress": 80}).progress == 0.8
    assert connector._map_document({"id": "1", "run": "UNSTART"}).status == "pending"
    # v1.0 的 ingestion_status 字段优先
    assert connector._map_document({"id": "1", "ingestion_status": "COMPLETED"}).ready
    assert connector._map_document({"id": "1", "ingestion_status": "FAILED"}).failed
    assert connector._map_document({"id": "1", "ingestion_status": "RUNNING"}).status == "running"
    assert connector._map_document({"id": "1", "ingestion_status": "CREATED"}).status == "pending"
    failed = connector._map_document(
        {"id": "1", "ingestion_status": "FAILED", "latest_ingestion_event": {"message": "chunk failed"}}
    )
    assert failed.error == "chunk failed"


def test_ragflow_parse_falls_back_to_0x_endpoint():
    calls = []
    routes = {
        ("POST", "/api/v1/documents/ingest"): lambda request: httpx.Response(
            404, json={"code": 404, "message": "Not Found"}
        ),
        ("POST", "/api/v1/datasets/kb1/chunks"): {"code": 0, "data": True},
    }
    connector = create_connector(
        "ragflow",
        {"api_endpoint": "http://ragflow.local"},
        transport=routes_transport(routes, calls),
    )
    asyncio_run(connector.trigger_parse("kb1", ["doc1"]))
    legacy = next(r for r in calls if r.url.path == "/api/v1/datasets/kb1/chunks")
    assert json.loads(legacy.content) == {"document_ids": ["doc1"]}


def test_ragflow_create_falls_back_to_0x_payload():
    calls = []

    def create_route(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if "parse_type" in body:
            return httpx.Response(
                200,
                json={"code": 102, "message": "Extra inputs are not permitted: parse_type"},
            )
        return httpx.Response(200, json={"code": 0, "data": {"id": "kb-legacy", "name": body["name"]}})

    connector = create_connector(
        "ragflow",
        {"api_endpoint": "http://ragflow.local"},
        transport=routes_transport({("POST", "/api/v1/datasets"): create_route}, calls),
    )
    kb = asyncio_run(connector.create_knowledge_base("旧版库", description="说明"))
    assert kb.id == "kb-legacy"
    bodies = [json.loads(r.content) for r in calls]
    assert bodies[0]["parse_type"] == 1
    assert bodies[1]["chunk_method"] == "naive"
    assert bodies[1]["description"] == "说明"


def test_ragflow_ask_falls_back_to_0x_chat_endpoint():
    calls = []
    routes = {
        ("POST", "/api/v1/chat/completions"): lambda request: httpx.Response(
            404, json={"code": 404, "message": "Not Found"}
        ),
        ("POST", "/api/v1/chats/chat1/completions"): {
            "code": 0,
            "data": {"answer": "七天无理由", "reference": {"chunks": []}},
        },
    }
    connector = create_connector(
        "ragflow",
        {
            "api_endpoint": "http://ragflow.local",
            "chat_llm": {"model_name": "qwen@jq@OpenAI-API-Compatible"},
        },
        transport=routes_transport(routes, calls),
    )
    answer = asyncio_run(connector.ask("怎么退款?", chat_id="chat1"))
    assert answer["answer"] == "七天无理由"
    first = next(r for r in calls if r.url.path == "/api/v1/chat/completions")
    body = json.loads(first.content)
    assert body["chat_id"] == "chat1"
    assert body["llm_id"] == "qwen@jq@OpenAI-API-Compatible"
    legacy = next(r for r in calls if r.url.path == "/api/v1/chats/chat1/completions")
    assert "chat_id" not in json.loads(legacy.content)


# --------------------------------------------------------------------- Dify


def test_dify_uses_separate_dataset_and_chat_keys():
    calls = []

    routes = {
        ("GET", "/v1/datasets"): {
            "data": [{"id": "kb1", "name": "FAQ"}],
            "has_more": False,
        },
        ("POST", "/v1/datasets/kb1/document/create-by-file"): {
            "document": {"id": "doc1", "name": "faq.md"},
            "batch": "batch-1",
        },
        ("GET", "/v1/datasets/kb1/documents/doc1/segments"): {
            "data": [
                {"id": "seg1", "content": "七天无理由", "position": 1, "document_id": "doc1"},
            ],
            "has_more": False,
        },
        ("POST", "/v1/chat-messages"): {
            "answer": "七天无理由",
            "metadata": {
                "retriever_resources": [
                    {"content": "七天无理由", "segment_id": "seg1", "dataset_id": "kb1"}
                ]
            },
        },
    }
    connector = create_connector(
        "dify",
        {
            "api_endpoint": "http://dify.local",
            "api_key": "app-xxx",
            "dataset_api_key": "dataset-xxx",
        },
        transport=routes_transport(routes, calls),
    )

    assert connector.api_root == "http://dify.local/v1"
    kbs = asyncio_run(connector.list_knowledge_bases())
    assert kbs[0].id == "kb1"

    uploaded = asyncio_run(connector.upload_document("kb1", "faq.md", b"hello", "text/markdown"))
    upload_request = next(r for r in calls if r.url.path.endswith("/document/create-by-file"))
    # 知识库接口必须用 dataset key
    assert upload_request.headers["authorization"] == "Bearer dataset-xxx"
    assert "multipart/form-data" in upload_request.headers["content-type"]
    assert uploaded.id == "doc1"

    chunks = asyncio_run(connector.list_chunks("kb1", "doc1"))
    assert [(c.id, c.content) for c in chunks] == [("seg1", "七天无理由")]

    answer = asyncio_run(connector.ask("可以退吗?"))
    chat_request = next(r for r in calls if r.url.path == "/v1/chat-messages")
    assert chat_request.headers["authorization"] == "Bearer app-xxx"
    assert answer["contexts"] == ["七天无理由"]
    assert answer["retrieval_ids"] == ["seg1"]


def test_dify_401_explains_two_key_model():
    connector = create_connector(
        "dify",
        {"api_endpoint": "http://dify.local", "api_key": "app-xxx"},
        transport=routes_transport(
            {("GET", "/v1/datasets"): lambda request: httpx.Response(401, json={"code": "unauthorized"})}
        ),
    )
    with pytest.raises(ConnectorError) as exc_info:
        asyncio_run(connector.list_knowledge_bases())
    assert "dataset" in str(exc_info.value).lower()
    assert "知识库 API Key" in str(exc_info.value)


def test_dify_high_quality_kb_requires_embedding_config():
    connector = create_connector("dify", {"api_endpoint": "http://dify.local"})
    with pytest.raises(ConnectorError) as exc_info:
        asyncio_run(connector.create_knowledge_base("新的库"))
    assert "embedding" in str(exc_info.value)


# ------------------------------------------------------------------ FastGPT


def test_fastgpt_unwraps_envelope_and_maps_collection_status():
    calls = []

    def list_v2(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["datasetId"] == "kb1"
        return httpx.Response(
            200,
            json={
                "code": 200,
                "data": {
                    "total": 3,
                    "list": [
                        {"_id": "c1", "name": "done.md", "trainingAmount": 2, "dataAmount": 2},
                        {"_id": "c2", "name": "pending.md", "trainingAmount": 2, "dataAmount": 0},
                        {"_id": "c3", "name": "error.md", "trainingStatus": "error"},
                    ],
                },
            },
        )

    routes = {
        ("POST", "/api/core/dataset/list"): {
            "code": 200,
            "data": [{"_id": "kb1", "name": "知识库"}],
        },
        ("POST", "/api/core/dataset/collection/create/localFile"): {
            "code": 200,
            "data": {"collectionId": "c1"},
        },
        ("POST", "/api/core/dataset/collection/listV2"): list_v2,
        ("POST", "/api/core/dataset/data/v2/list"): {
            "code": 200,
            "data": {
                "total": 1,
                "list": [{"_id": "d1", "q": "退款政策", "index": 0}],
            },
        },
        ("POST", "/api/v1/chat/completions"): {
            "choices": [
                {
                    "message": {"content": "七天无理由"},
                    "responseData": [
                        {"quoteList": [{"id": "d1", "q": "退款政策"}]}
                    ],
                }
            ]
        },
    }
    connector = create_connector(
        "fastgpt",
        {"api_endpoint": "http://fastgpt.local:3000", "api_key": "fastgpt-key"},
        transport=routes_transport(routes, calls),
    )

    assert connector.api_root == "http://fastgpt.local:3000/api"

    kbs = asyncio_run(connector.list_knowledge_bases())
    assert kbs[0].id == "kb1"

    uploaded = asyncio_run(connector.upload_document("kb1", "faq.md", b"hello"))
    upload_request = next(r for r in calls if r.url.path.endswith("/create/localFile"))
    assert "multipart/form-data" in upload_request.headers["content-type"]
    # localFile 接口把 datasetId 等参数放在名为 data 的 JSON 表单字段里
    assert b'"datasetId": "kb1"' in upload_request.content
    assert uploaded.id == "c1"

    documents = {doc.id: doc for doc in asyncio_run(connector.list_documents("kb1"))}
    assert documents["c1"].status == "done"
    assert documents["c2"].status == "running"
    assert documents["c3"].failed

    chunks = asyncio_run(connector.list_chunks("kb1", "c1"))
    assert [(c.id, c.content) for c in chunks] == [("d1", "退款政策")]

    answer = asyncio_run(connector.ask("怎么退款?"))
    assert answer["answer"] == "七天无理由"
    assert answer["contexts"] == ["退款政策"]
    assert answer["retrieval_ids"] == ["d1"]


def test_fastgpt_error_envelope_raises():
    connector = create_connector(
        "fastgpt",
        {"api_endpoint": "http://fastgpt.local:3000"},
        transport=routes_transport(
            {("POST", "/api/core/dataset/list"): {"code": 403, "message": "invalid key"}}
        ),
    )
    with pytest.raises(ConnectorError) as exc_info:
        asyncio_run(connector.list_knowledge_bases())
    assert "code=403" in str(exc_info.value)


# --------------------------------------------------------------------- Coze


def test_coze_create_upload_then_chat_polling():
    calls = []
    poll = {"count": 0}

    def retrieve(request: httpx.Request) -> httpx.Response:
        poll["count"] += 1
        status = "in_progress" if poll["count"] < 2 else "completed"
        return httpx.Response(200, json={"code": 0, "data": {"status": status}})

    routes = {
        ("POST", "/v1/datasets"): {"code": 0, "data": {"dataset_id": "ds1"}},
        ("POST", "/open_api/knowledge/document/create"): {
            "code": 0,
            "data": {"document_infos": [{"document_id": "doc1", "name": "faq.md"}]},
        },
        ("POST", "/open_api/knowledge/document/list"): {
            "code": 0,
            "data": {
                "total": 1,
                "document_infos": [{"document_id": "doc1", "name": "faq.md", "status": 1}],
            },
        },
        ("POST", "/v3/chat"): {
            "code": 0,
            "data": {"id": "chat1", "conversation_id": "conv1", "status": "in_progress"},
        },
        ("GET", "/v3/chat/retrieve"): retrieve,
        ("GET", "/v3/chat/message/list"): {
            "code": 0,
            "data": [
                {"type": "answer", "content": "七天无理由", "role": "assistant"},
                {"type": "knowledge", "content": "退款政策是七天无理由"},
            ],
        },
    }
    connector = create_connector(
        "coze",
        {
            "api_endpoint": "https://api.coze.cn",
            "api_key": "pat_x",
            "space_id": "space-1",
            "bot_id": "bot-1",
            "poll_interval": 0.001,
        },
        transport=routes_transport(routes, calls),
    )

    kb = asyncio_run(connector.create_knowledge_base("Coze 库"))
    create_request = next(r for r in calls if r.url.path == "/v1/datasets")
    assert json.loads(create_request.content)["space_id"] == "space-1"
    assert kb.id == "ds1"

    uploaded = asyncio_run(connector.upload_document("ds1", "faq.md", "退款政策".encode("utf-8")))
    upload_request = next(r for r in calls if r.url.path.endswith("/document/create"))
    body = json.loads(upload_request.content)
    import base64

    assert base64.b64decode(body["document_bases"][0]["source_info"]["file_base64"]).decode() == "退款政策"
    assert upload_request.headers["Agw-Js-Conv"] == "str"
    assert uploaded.id == "doc1"

    documents = asyncio_run(connector.list_documents("ds1"))
    assert documents[0].ready

    # Coze 不开放分片接口：能力声明为 False，且直接返回空列表
    assert connector.capabilities.list_chunks is False
    assert asyncio_run(connector.list_chunks("ds1", "doc1")) == []

    answer = asyncio_run(connector.ask("怎么退款?"))
    assert answer["answer"] == "七天无理由"
    assert answer["contexts"] == ["退款政策是七天无理由"]
    assert poll["count"] >= 2


def test_coze_requires_space_id_and_bot_id():
    connector = create_connector("coze", {"api_endpoint": "https://api.coze.cn", "api_key": "pat"})
    with pytest.raises(ConnectorError) as exc_info:
        asyncio_run(connector.create_knowledge_base("库"))
    assert "space_id" in str(exc_info.value)

    with pytest.raises(ConnectorError) as exc_info:
        asyncio_run(connector.ask("hello"))
    assert "bot_id" in str(exc_info.value)


# --------------------------------------------------------------- PageIndex


def test_pageindex_uploads_polls_tree_and_asks():
    calls = []
    routes = {
        ("GET", "/docs"): {
            "documents": [{"id": "pi-1", "name": "policy.pdf", "status": "completed"}],
            "total": 1,
            "limit": 100,
            "offset": 0,
        },
        ("POST", "/doc/"): {"doc_id": "pi-2"},
        ("GET", "/doc/pi-2/"): {
            "doc_id": "pi-2",
            "status": "completed",
            "result": [
                {
                    "title": "报销",
                    "node_id": "0001",
                    "page_index": 3,
                    "text": "一线城市住宿上限 600 元",
                    "nodes": [{"node_id": "0002", "page_index": 4, "text": "二线城市 400 元"}],
                }
            ],
        },
        ("POST", "/chat/completions"): {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "600 元",
                        "citations": [{"node_id": "0001", "text": "一线城市住宿上限 600 元"}],
                    }
                }
            ]
        },
    }
    connector = create_connector(
        "pageindex",
        {"api_endpoint": "https://api.pageindex.ai", "api_key": "pi-key"},
        transport=routes_transport(routes, calls),
    )

    kbs = asyncio_run(connector.list_knowledge_bases())
    assert kbs[0].id == "pageindex:account"
    assert kbs[0].raw["documents"][0]["id"] == "pi-1"

    uploaded = asyncio_run(
        connector.upload_document("pageindex:account", "policy.pdf", b"%PDF-1.4")
    )
    assert uploaded.id == "pi-2"

    # 上传即建树，trigger_parse 是空操作，不应产生额外请求
    before = len(calls)
    asyncio_run(connector.trigger_parse("pageindex:account", ["pi-2"]))
    assert len(calls) == before

    documents = asyncio_run(connector.list_documents("pageindex:account"))
    assert documents[0].id == "pi-1" and documents[0].ready

    chunks = asyncio_run(connector.list_chunks("pageindex:account", "pi-2"))
    assert [chunk.id for chunk in chunks] == ["pi-2:0001", "pi-2:0002"]
    assert chunks[0].index == 3

    answer = asyncio_run(connector.ask("住宿上限?", chat_id="pageindex:account"))
    assert answer["answer"] == "600 元"
    assert answer["contexts"] == ["一线城市住宿上限 600 元"]
    assert answer["retrieval_ids"] == ["0001"]

    # PageIndex 用 api_key 请求头，不是 Bearer
    docs_request = next(r for r in calls if r.url.path == "/docs")
    assert docs_request.headers["api_key"] == "pi-key"
    assert "authorization" not in docs_request.headers


def test_pageindex_document_status_mapping():
    connector = create_connector("pageindex", {"api_key": "pi-key"})
    assert connector._map_document({"id": "1", "status": "processing"}).status == "running"
    assert connector._map_document({"id": "1", "status": "completed"}).ready
    failed = connector._map_document({"id": "1", "status": "failed", "error": "bad pdf"})
    assert failed.failed and failed.error == "bad pdf"


# ---------------------------------------------------------------- LLM Wiki


def test_llm_wiki_writes_page_embeds_and_chats():
    calls = []
    routes = {
        ("GET", "/api/v1/projects"): {
            "projects": [{"id": "p1", "name": "个人知识库", "path": "D:/wiki", "current": True}],
            "currentProject": {"id": "p1", "name": "个人知识库", "path": "D:/wiki", "current": True},
        },
        ("POST", "/api/v1/projects/p1/pages/write"): {
            "result": {
                "path": "wiki/imports/faq.md",
                "bytes": 12,
                "allowOverwrite": True,
                "verified": True,
                "existedBefore": False,
            }
        },
        ("POST", "/api/v1/projects/p1/pages/embed"): {
            "result": {
                "path": "wiki/imports/faq.md",
                "pageId": "page-1",
                "revision": "r1",
                "chunks": 3,
                "vectorsWritten": 3,
                "status": "ok",
            }
        },
        ("GET", "/api/v1/projects/p1/files"): {
            "files": [
                {
                    "name": "imports",
                    "path": "wiki/imports",
                    "isDir": True,
                    "children": [
                        {"name": "faq.md", "path": "wiki/imports/faq.md", "isDir": False}
                    ],
                }
            ]
        },
        ("POST", "/api/v1/projects/p1/chat"): {
            "projectId": "p1",
            "sessionId": "s1",
            "message": {"role": "assistant", "content": "七天无理由"},
            "references": [
                {
                    "title": "退款 FAQ",
                    "path": "wiki/imports/faq.md",
                    "kind": "wiki",
                    "snippet": "七天无理由退货",
                }
            ],
        },
    }
    connector = create_connector(
        "llm_wiki",
        {
            "api_endpoint": "http://127.0.0.1:19828",
            "api_key": "wiki-token",
        },
        transport=routes_transport(routes, calls),
    )

    kbs = asyncio_run(connector.list_knowledge_bases())
    assert kbs[0].id == "p1"

    uploaded = asyncio_run(
        connector.upload_document("p1", "faq.md", "# 退款\n七天无理由".encode())
    )
    assert uploaded.id == "wiki/imports/faq.md"
    assert uploaded.ready

    write_request = next(r for r in calls if r.url.path.endswith("/pages/write"))
    assert write_request.headers["authorization"] == "Bearer wiki-token"
    assert json.loads(write_request.content)["path"] == "wiki/imports/faq.md"

    documents = asyncio_run(connector.list_documents("p1"))
    assert [doc.id for doc in documents] == ["wiki/imports/faq.md"]

    answer = asyncio_run(connector.ask("怎么退款?", chat_id="p1"))
    assert answer["answer"] == "七天无理由"
    assert answer["contexts"] == ["七天无理由退货"]
    assert answer["retrieval_ids"] == ["wiki/imports/faq.md"]
    chat_request = next(r for r in calls if r.url.path.endswith("/chat"))
    chat_body = json.loads(chat_request.content)
    assert chat_body["tools"]["wiki"] is True
    assert chat_body["tools"]["web"] is False


def test_llm_wiki_rejects_binary_documents():
    connector = create_connector("llm_wiki", {"api_endpoint": "http://127.0.0.1:19828"})
    with pytest.raises(ConnectorError) as exc_info:
        asyncio_run(connector.upload_document("p1", "scan.pdf", b"\xff\xfe\x00binary"))
    assert "PDF" in str(exc_info.value)


# --------------------------------------------------------------- 通用 profile


def test_generic_openai_compatible_ask():
    calls = []
    connector = create_connector(
        "openai_compatible",
        {"api_endpoint": "http://gateway.local/v1", "api_key": "sk-x", "model": "qwen-plus"},
        transport=routes_transport(
            {
                ("POST", "/v1/chat/completions"): {
                    "choices": [
                        {
                            "message": {
                                "content": "答案",
                                "contexts": ["上下文 A"],
                                "retrieval_ids": ["chunk-1"],
                            }
                        }
                    ]
                }
            },
            calls,
        ),
    )

    answer = asyncio_run(connector.ask("问题"))
    request = calls[0]
    assert request.headers["authorization"] == "Bearer sk-x"
    assert json.loads(request.content)["model"] == "qwen-plus"
    assert answer["answer"] == "答案"
    assert answer["contexts"] == ["上下文 A"]
    assert answer["retrieval_ids"] == ["chunk-1"]


def test_generic_user_profile_overrides_preset():
    connector = create_connector(
        "volcengine_ark",
        {
            "api_endpoint": "http://my-ark.local",
            "model": "bot-123",
            # 用户自定义 profile 应覆盖内置预设路径
            "ingest_profile": {
                "ask": {
                    "path": "/custom/chat",
                    "body": {"model": "{{model}}", "q": "{{question}}"},
                    "answer_path": "result.text",
                }
            },
        },
    )
    assert connector.profile["ask"]["path"] == "/custom/chat"
    assert connector.capabilities.ask is True


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


# ============================================================ 开源系统连接器
# 这一组锁住「主流开源 >1k star 方案」的请求形状；真实部署未联调的仍然
# 在 registry 里标 verified=False，测试通过不等于上游版本一定兼容。


def test_anythingllm_workspace_upload_and_chat():
    calls = []
    connector = create_connector(
        "anythingllm",
        {"api_endpoint": "http://localhost:3001", "api_key": "al-key"},
        transport=routes_transport(
            {
                ("GET", "/api/v1/workspaces"): {
                    "workspaces": [{"slug": "kb1", "name": "知识库"}]
                },
                ("POST", "/api/v1/workspace/new"): {
                    "workspace": {"slug": "kb-new", "name": "新建库"}
                },
                ("POST", "/api/v1/document/upload"): {
                    "success": True,
                    "documents": [
                        {
                            "location": "custom-documents/faq.md-abc.json",
                            "title": "faq.md",
                        }
                    ],
                },
                ("GET", "/api/v1/workspace/kb-new"): {
                    "workspace": {
                        "documents": [
                            {
                                "docpath": "custom-documents/faq.md-abc.json",
                                "title": "faq.md",
                            }
                        ]
                    }
                },
                ("POST", "/api/v1/workspace/kb-new/chat"): {
                    "textResponse": "七天无理由退货",
                    "sources": [{"chunk": "退款政策是七天无理由", "title": "faq.md"}],
                },
            },
            calls,
        ),
    )

    assert [kb.id for kb in asyncio_run(connector.list_knowledge_bases())] == ["kb1"]
    kb = asyncio_run(connector.create_knowledge_base("新建库"))
    assert kb.id == "kb-new"
    doc = asyncio_run(connector.upload_document("kb-new", "faq.md", b"hello"))
    assert doc.id.endswith("faq.md-abc.json")
    assert doc.ready

    upload_call = next(c for c in calls if c.url.path == "/api/v1/document/upload")
    assert b"addToWorkspaces" in upload_call.content
    assert upload_call.headers["authorization"] == "Bearer al-key"

    documents = asyncio_run(connector.list_documents("kb-new"))
    assert documents[0].id == doc.id

    answer = asyncio_run(connector.ask("退款政策?", chat_id="kb-new"))
    assert answer["answer"] == "七天无理由退货"
    assert answer["contexts"] == ["退款政策是七天无理由"]


def test_open_webui_knowledge_upload_and_chat():
    calls = []
    connector = create_connector(
        "open_webui",
        {
            "api_endpoint": "http://localhost:3000",
            "api_key": "owui-key",
            "model": "qwen2.5:7b",
        },
        transport=routes_transport(
            {
                ("GET", "/api/v1/knowledge/"): {
                    "items": [{"id": "kb1", "name": "知识库"}],
                    "total": 1,
                },
                ("POST", "/api/v1/knowledge/create"): {"id": "kb-new", "name": "新建库"},
                ("POST", "/api/v1/files/"): {"id": "file1", "filename": "faq.md"},
                ("POST", "/api/v1/knowledge/kb-new/file/add"): {
                    "files": [{"id": "file1", "filename": "faq.md"}]
                },
                ("GET", "/api/v1/knowledge/kb-new"): {
                    "files": [{"id": "file1", "filename": "faq.md"}]
                },
                ("POST", "/api/chat/completions"): {
                    "choices": [{"message": {"content": "答案"}}],
                    "sources": [{"content": "命中的分片", "document_id": "c1"}],
                },
            },
            calls,
        ),
    )

    assert asyncio_run(connector.list_knowledge_bases())[0].id == "kb1"
    assert asyncio_run(connector.create_knowledge_base("新建库")).id == "kb-new"
    doc = asyncio_run(connector.upload_document("kb-new", "faq.md", b"hello"))
    assert doc.id == "file1" and doc.ready
    assert asyncio_run(connector.list_documents("kb-new"))[0].id == "file1"

    answer = asyncio_run(connector.ask("问题", chat_id="kb-new"))
    assert answer["answer"] == "答案"
    assert answer["contexts"] == ["命中的分片"]

    chat_call = next(c for c in calls if c.url.path == "/api/chat/completions")
    body = json.loads(chat_call.content)
    assert body["files"] == [{"type": "collection", "id": "kb-new"}]


def test_maxkb_dataset_paragraphs_and_application_chat():
    calls = []
    connector = create_connector(
        "maxkb",
        {
            "api_endpoint": "http://localhost:8080",
            "api_key": "app-key",
            "dataset_api_key": "dataset-key",
            "application_id": "app1",
        },
        transport=routes_transport(
            {
                ("GET", "/api/dataset"): {
                    "code": 200,
                    "data": {"records": [{"id": "kb1", "name": "知识库"}]},
                },
                ("POST", "/api/dataset"): {
                    "code": 200,
                    "data": {"id": "kb-new", "name": "新建库"},
                },
                ("POST", "/api/dataset/kb-new/document"): {
                    "code": 200,
                    "data": {"id": "doc1", "name": "faq.md"},
                },
                ("GET", "/api/dataset/kb-new/document"): {
                    "code": 200,
                    "data": {
                        "records": [
                            {"id": "doc1", "name": "faq.md", "status": "SUCCESS"}
                        ]
                    },
                },
                ("GET", "/api/dataset/kb-new/document/doc1/paragraph"): {
                    "code": 200,
                    "data": {"records": [{"id": "p1", "content": "分片内容"}]},
                },
                ("POST", "/api/application/app1/chat/completions"): {
                    "code": 200,
                    "data": {
                        "choices": [{"message": {"content": "答案"}}],
                        "references": [{"id": "p1", "content": "分片内容"}],
                    },
                },
            },
            calls,
        ),
    )

    assert asyncio_run(connector.list_knowledge_bases())[0].id == "kb1"
    assert asyncio_run(connector.create_knowledge_base("新建库")).id == "kb-new"
    doc = asyncio_run(connector.upload_document("kb-new", "faq.md", b"hello"))
    assert doc.id == "doc1"
    assert asyncio_run(connector.list_documents("kb-new"))[0].ready
    assert asyncio_run(connector.list_chunks("kb-new", "doc1"))[0].content == "分片内容"

    answer = asyncio_run(connector.ask("问题"))
    assert answer["answer"] == "答案"
    assert answer["contexts"] == ["分片内容"]

    dataset_call = next(c for c in calls if c.url.path == "/api/dataset/kb-new/document")
    assert dataset_call.headers["authorization"] == "Bearer dataset-key"
    app_call = next(c for c in calls if c.url.path == "/api/application/app1/chat/completions")
    assert app_call.headers["authorization"] == "Bearer app-key"


def test_lightrag_upload_poll_chunks_and_query():
    connector = create_connector(
        "lightrag",
        {"api_endpoint": "http://localhost:9621", "api_key": "lr-key"},
        transport=routes_transport(
            {
                ("POST", "/documents"): {"status": "success", "track_id": "track1"},
                ("GET", "/documents"): {
                    "statuses": {
                        "doc1": {"status": "processed", "file_path": "faq.md"}
                    }
                },
                ("GET", "/chunks"): {
                    "chunks": [
                        {"id": "c1", "content": "分片内容", "chunk_order_index": 0}
                    ]
                },
                ("POST", "/query"): {
                    "response": "答案",
                    "references": [{"reference_id": "c1", "content": "分片内容"}],
                },
            },
        ),
    )

    kb = asyncio_run(connector.list_knowledge_bases())[0]
    assert kb.id == "lightrag:account"
    doc = asyncio_run(connector.upload_document(kb.id, "faq.md", b"hello"))
    assert doc.id == "doc1"
    assert asyncio_run(connector.list_documents(kb.id))[0].ready
    assert asyncio_run(connector.list_chunks(kb.id, "doc1"))[0].id == "c1"

    answer = asyncio_run(connector.ask("问题"))
    assert answer["answer"] == "答案"
    assert answer["contexts"] == ["分片内容"]


def test_langchain_chatchat_kb_upload_and_chat():
    connector = create_connector(
        "langchain_chatchat",
        {"api_endpoint": "http://localhost:7861", "api_key": "cc-key"},
        transport=routes_transport(
            {
                ("GET", "/knowledge_base/list_knowledge_bases"): {"data": ["kb1"]},
                ("POST", "/knowledge_base/create_knowledge_base"): {"code": 200},
                ("POST", "/knowledge_base/upload_docs"): {
                    "code": 200,
                    "data": {"loaded_files": ["faq.md"], "failed_files": []},
                },
                ("GET", "/knowledge_base/list_files"): {
                    "data": [{"file_name": "faq.md"}]
                },
                ("POST", "/chat/chat"): {
                    "answer": "答案",
                    "docs": [
                        {
                            "page_content": "分片内容",
                            "metadata": {"source": "faq.md"},
                        }
                    ],
                },
            },
        ),
    )

    assert asyncio_run(connector.list_knowledge_bases())[0].id == "kb1"
    assert asyncio_run(connector.create_knowledge_base("新建库")).id == "新建库"
    doc = asyncio_run(connector.upload_document("kb1", "faq.md", b"hello"))
    assert doc.id == "faq.md" and doc.ready
    assert asyncio_run(connector.list_documents("kb1"))[0].id == "faq.md"

    answer = asyncio_run(connector.ask("问题", chat_id="kb1"))
    assert answer["answer"] == "答案"
    assert answer["contexts"] == ["分片内容"]


def test_qanything_kb_upload_and_chat():
    connector = create_connector(
        "qanything",
        {"api_endpoint": "http://localhost:8777"},
        transport=routes_transport(
            {
                ("POST", "/api/local_doc_qa/list_kbs"): {
                    "code": 200,
                    "data": [{"kb_id": "kb1", "kb_name": "知识库"}],
                },
                ("POST", "/api/local_doc_qa/create_kb"): {
                    "code": 200,
                    "data": {"kb_id": "kb-new", "kb_name": "新建库"},
                },
                ("POST", "/api/local_doc_qa/upload_files"): {
                    "code": 200,
                    "data": [{"file_id": "doc1", "file_name": "faq.md"}],
                },
                ("POST", "/api/local_doc_qa/list_files"): {
                    "code": 200,
                    "data": [
                        {"file_id": "doc1", "file_name": "faq.md", "status": "success"}
                    ],
                },
                ("POST", "/api/local_doc_qa/chat"): {
                    "response": "答案",
                    "source_documents": [{"content": "分片内容", "file_id": "doc1"}],
                },
            },
        ),
    )

    assert asyncio_run(connector.list_knowledge_bases())[0].id == "kb1"
    assert asyncio_run(connector.create_knowledge_base("新建库")).id == "kb-new"
    doc = asyncio_run(connector.upload_document("kb-new", "faq.md", b"hello"))
    assert doc.id == "doc1"
    assert asyncio_run(connector.list_documents("kb-new"))[0].ready

    answer = asyncio_run(connector.ask("问题", chat_id="kb-new"))
    assert answer["answer"] == "答案"
    assert answer["contexts"] == ["分片内容"]


def test_privategpt_ingest_and_chat():
    connector = create_connector(
        "privategpt",
        {"api_endpoint": "http://localhost:8001", "model": "private-gpt"},
        transport=routes_transport(
            {
                ("POST", "/v1/ingest"): {"id": "doc1", "object": "ingest"},
                ("POST", "/v1/chat/completions"): {
                    "choices": [{"message": {"content": "答案"}}],
                    "sources": [{"content": "分片内容", "id": "c1"}],
                },
            },
        ),
    )
    doc = asyncio_run(connector.upload_document("privategpt:account", "faq.md", b"hello"))
    assert doc.id == "doc1" and doc.ready
    assert asyncio_run(connector.list_documents("privategpt:account"))[0].id == "doc1"
    answer = asyncio_run(connector.ask("问题"))
    assert answer["answer"] == "答案"
    assert answer["contexts"] == ["分片内容"]


def test_r2r_documents_chunks_and_retrieval():
    connector = create_connector(
        "r2r",
        {"api_endpoint": "http://localhost:7272", "api_key": "r2r-key"},
        transport=routes_transport(
            {
                ("POST", "/v3/documents"): {
                    "results": {"document_id": "doc1", "title": "faq.md"}
                },
                ("GET", "/v3/documents"): {
                    "results": [
                        {"id": "doc1", "title": "faq.md", "status": "success"}
                    ]
                },
                ("GET", "/v3/documents/doc1/chunks"): {
                    "results": [{"id": "c1", "text": "分片内容", "chunk_order": 0}]
                },
                ("POST", "/v3/retrieval"): {
                    "generated_answer": "答案",
                    "results": {
                        "chunk_search_results": [{"id": "c1", "text": "分片内容"}]
                    },
                },
            },
        ),
    )
    doc = asyncio_run(connector.upload_document("r2r:account", "faq.md", b"hello"))
    assert doc.id == "doc1"
    assert asyncio_run(connector.list_documents("r2r:account"))[0].ready
    assert asyncio_run(connector.list_chunks("r2r:account", "doc1"))[0].content == "分片内容"
    answer = asyncio_run(connector.ask("问题"))
    assert answer["answer"] == "答案"
    assert answer["contexts"] == ["分片内容"]


def test_docsgpt_upload_and_chat():
    connector = create_connector(
        "docsgpt",
        {"api_endpoint": "http://localhost:5001"},
        transport=routes_transport(
            {
                ("POST", "/api/upload"): {"success": True, "message": "ok"},
                ("GET", "/api/docs"): {"docs": [{"name": "faq.md"}]},
                ("POST", "/api/chat"): {
                    "answer": "答案",
                    "sources": [{"text": "分片内容", "title": "faq.md"}],
                },
            },
        ),
    )
    doc = asyncio_run(connector.upload_document("docsgpt:account", "faq.md", b"hello"))
    assert doc.id == "faq.md"
    assert asyncio_run(connector.list_documents("docsgpt:account"))[0].id == "faq.md"
    answer = asyncio_run(connector.ask("问题"))
    assert answer["answer"] == "答案"
    assert answer["contexts"] == ["分片内容"]


def test_khoj_upload_and_chat():
    connector = create_connector(
        "khoj",
        {"api_endpoint": "http://localhost:42110", "api_key": "kk-key"},
        transport=routes_transport(
            {
                ("PUT", "/api/content/"): {"success": True},
                ("POST", "/api/chat"): {
                    "response": "答案",
                    "references": [
                        {
                            "additional": {
                                "file": "faq.md",
                                "compiled": "分片内容",
                            }
                        }
                    ],
                },
            },
        ),
    )
    doc = asyncio_run(connector.upload_document("khoj:account", "faq.md", b"hello"))
    assert doc.id == "faq.md"
    assert asyncio_run(connector.list_documents("khoj:account"))[0].id == "faq.md"
    answer = asyncio_run(connector.ask("问题"))
    assert answer["answer"] == "答案"
    assert answer["contexts"] == ["分片内容"]


# --------------------------------------------------------------- 覆盖清单


def test_catalog_lists_all_supported_types_and_reasons():
    from app.services.api_ingest import list_catalog

    data = list_catalog()
    items = {item["system_type"]: item for item in data["items"] if item.get("system_type")}
    types = {item["system_type"]: item for item in list_connector_types()}

    # 每个已接入的类型都必须在清单里有 star / repo / 覆盖说明
    for system_type in types:
        if system_type in ("generic", "coze"):
            continue
        if system_type not in items:
            # 百度/阿里/腾讯/字节/讯飞等闭源商业云不在“开源 >1k star”清单里，
            # 但必须有 profile 说明，避免被误认为遗漏。
            assert types[system_type]["capabilities"]["notes"]
            continue
        assert system_type in items, f"{system_type} 未出现在 >1k star 清单"
        assert items[system_type]["stars"] > 1000
        assert items[system_type]["repo"]
        assert items[system_type]["notes"]

    # 明确排除的也要写原因，不能静默消失
    excluded = [item for item in data["items"] if item["integration"] == "excluded"]
    assert excluded
    assert all(item["notes"] for item in excluded)
    assert data["summary"]["star_snapshot"] == "2026-10-28"
    assert data["summary"]["covered"] >= 18


def test_adapter_factory_reuses_ingest_connectors_for_new_types():
    from app.services.adapters import AdapterFactory

    adapter = AdapterFactory.create(
        "anythingllm",
        {"api_endpoint": "http://localhost:3001", "api_key": "k"},
    )
    assert adapter.connector.display_name == "AnythingLLM"

    adapter = AdapterFactory.create(
        "pageindex",
        {"api_endpoint": "https://api.pageindex.ai", "api_key": "k"},
    )
    assert adapter.connector.display_name == "PageIndex"

