# API 全链路入库接入

> 状态：核心实现完成，离线契约测试通过（`tests/test_api_ingest.py`，35 例）。
> RAGFlow 已在本地 v1.0.0-rc2 用真实 embedding + 真实 LLM 跑通
> 建库→上传→解析→分片→向量检索→问答全链路（见 4.1）。
> PageIndex / LLM Wiki 已按官方接口实现（见 4.2），**尚未实机验证**；
> 2026-10 新增的 AnythingLLM / Open WebUI / MaxKB / LightRAG / Langchain-Chatchat /
> QAnything / PrivateGPT / DocsGPT / R2R / Khoj 均按官方 API 实现，**尚未逐一实机联调**；
> 云端平台（百度/阿里/腾讯/字节/讯飞）均按官方文档实现，**尚未用真实账号验证**，见能力矩阵的「验证状态」。
> 「>1k star 开源方案」的纳入/排除口径见 4.3，机器可读清单见
> `GET /api/v1/rag-systems/ingest-catalog`。

## 1. 为什么有这条链路

旧「数据源同步」是数据库直连：读对方 MySQL/Mongo 里的分片和消息，复制一份到 jq-eval。
问题是它绕过了被测系统的解析、切分、向量化和检索配置——评测时拿到的上下文，
和用户真实提问时系统召回的内容并不是同一份。

API 全链路入库改为走对方官方 HTTP API：

```
建库/选库 → 上传原始文档 → 触发解析 → 轮询解析状态
          → 拉取远端分片 → 落本地 Document/Chunk → 生成或导入 QA
          → （可选）自动批量调用 → 生成评测数据集
```

这样 QA 的 `snapshot.contexts` 和 `target_chunk_ids` 都指向被测系统**实际产出的分片**，
Recall@K / MRR / 引用命中才有真实对照物。

旧数据库同步代码保留但已标记废弃：`/api/v1/data-sources/supported-systems` 返回
`deprecated: true`，前端「数据源」页顶部有提示。

## 2. 入口

前端：`RAG 系统` 页面 → 对应系统行 →「API 入库」。
后端：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/rag-systems/ingest-types` | 支持的系统类型与能力清单 |
| GET | `/api/v1/rag-systems/ingest-catalog` | >1k star 开源方案覆盖清单（含排除原因、star 快照） |
| GET | `/api/v1/rag-systems/{id}/ingest/capabilities` | 单个连接的能力与连通性 |
| GET | `/api/v1/rag-systems/{id}/knowledge-bases` | 远端知识库列表 |
| POST | `/api/v1/rag-systems/{id}/knowledge-bases` | 新建远端知识库（body: `name`/`description`/`space_id`） |
| POST | `/api/v1/rag-systems/{id}/ingest` | multipart 上传并启动入库任务 |
| GET | `/api/v1/rag-systems/{id}/ingest-tasks` | 该系统的入库任务列表 |
| GET | `/api/v1/rag-systems/ingest-tasks/{task_id}` | 任务进度/阶段/错误 |

`POST /ingest` 表单字段：

- `files`：原始文档（可多个）
- `kb_id` / `new_kb_name` / `space_id`：选择已有库、新建库或 Coze 空间
- `dataset_name`：jq-eval 本地数据集名（默认按知识库名+时间生成）
- `auto_generate`、`test_size`、`llm_model_id`、`embedding_model_id`：用 `DatasetGenerator` 生成 QA
- `auto_invoke`：入库完成后自动对被评测系统发起一轮调用
- `parse_timeout`：解析轮询超时（秒）

也可以直接把现成 QA 以 JSON 放在表单 `questions` 字段（前端高级选项未暴露时可用 API 调用），
格式与数据集导入一致；任务会跳过生成步骤。

## 3. 连接配置字段

在 RAG 系统编辑弹窗里按类型显示：

| 字段 | 适用 | 说明 |
| --- | --- | --- |
| `api_endpoint` | 全部 | 系统根地址，可带或不带 `/api/v1`、`/v1` |
| `api_key` | 全部 | 默认 Bearer；Dify/FastGPT 下作为应用 key |
| `dataset_api_key` | Dify / FastGPT / MaxKB | 知识库维护 key（Dify 为 `dataset-xxx`，MaxKB 为知识库 API Key） |
| `chat_id` | RAGFlow / FastGPT / AnythingLLM / Open WebUI | 会话助手 / 应用 chatId / workspace slug / knowledge collection ID |
| `dataset_id` / `space_id` | Coze | 已有知识库 ID / 空间 ID |
| `bot_id` / `app_id` / `application_id` | Coze / 百炼 / 元器 / MaxKB | Bot、应用或 MaxKB 应用标识 |
| `chatflow_id` / `flow_id` | Flowise / Langflow | 编排平台里的聊天流/流程 ID |
| `user_id` | QAnything | 文档隔离用户，默认 `jq-eval` |
| `model` | 通用 profile / Open WebUI / PrivateGPT / R2R / DB-GPT / Chatchat | 模型 ID；Open WebUI 必填 |
| `ingest_profile` | generic 及云平台覆盖 | JSON，覆盖内置请求/响应路径 |
| `llm_timeout` | 全部 | 问答超时秒数 |

## 4. 能力矩阵

`verified` 指「已在本地私有化部署上跑通」；`—` 表示该平台未开放对应接口。

| 系统 | 列库 | 建库 | 上传 | 触发解析 | 拉分片 | 问答 | 验证状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RAGFlow | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 本地 v1.0.0-rc2 真实 embedding+LLM 全链路实测通过（见 4.1） |
| Dify | ✓ | ✓* | ✓ | 自动 | ✓ | ✓ | 本地部署待联调 |
| FastGPT | ✓ | ✓ | ✓ | 自动训练 | ✓ | ✓ | 未联调 |
| Coze（扣子） | — | ✓ | ✓ | 自动 | — | ✓ | 未联调（无真实 key） |
| PageIndex | ✓（账号文档库） | — | ✓ | 自动建树 | ✓（树节点） | ✓ | 按官方 API 实现，未验证（云端无 key） |
| LLM Wiki | ✓（项目） | — | ✓（写 wiki 页） | 自动 embed | — | ✓ | 按官方本地 API 实现，未验证（需桌面端运行） |
| AnythingLLM | ✓（workspace） | ✓ | ✓ | 上传即嵌入 | — | ✓ | 按官方 API 实现，未联调 |
| Open WebUI | ✓（knowledge） | ✓ | ✓ | 加入知识库即嵌入 | — | ✓ | 按官方 API 实现，未联调；问答需 `model` |
| MaxKB | ✓ | ✓ | ✓ | 自动 | ✓（paragraph） | ✓ | 按官方 API 实现，未联调；知识库/应用两把 Key |
| LightRAG | ✓（虚拟库） | — | ✓ | 自动建图/向量 | ✓（/chunks） | ✓ | 按 lightrag-server 实现，未联调 |
| Langchain-Chatchat | ✓ | ✓ | ✓ | 上传即写向量库 | — | ✓ | 按 API Server 实现，未联调 |
| QAnything | ✓ | ✓ | ✓ | 自动 | — | ✓ | 按本地 API 实现，未联调 |
| PrivateGPT | ✓（虚拟库） | — | ✓ | 自动 | — | ✓ | 按官方 API 实现，未联调 |
| DocsGPT | ✓（虚拟库） | — | ✓ | 自动 | — | ✓ | 按官方 API 实现，未联调 |
| R2R | ✓（虚拟库） | — | ✓ | 自动 | ✓ | ✓ | 按 v3 契约实现，未联调；仓库近一年未更新 |
| Khoj | ✓（虚拟库） | — | ✓ | 自动 | — | ✓ | 按官方 API 实现，未联调 |
| Flowise（已归档） | — | — | — | — | — | ✓ | 仅 prediction 问答；需 `chatflow_id` |
| DB-GPT | — | — | — | — | — | ✓ | OpenAI 兼容问答；知识库在 DB-GPT 内配置 |
| Langflow | — | — | — | — | — | ✓ | 仅流程问答；需 `flow_id` |
| 百度千帆 AppBuilder | 按 profile | 按 profile | — | — | — | ✓ | 按文档，未验证 |
| 阿里云百炼 | — | — | — | — | — | ✓ | 按文档，未验证（知识库为 AK/SK 签名） |
| 腾讯混元 | — | — | — | — | — | ✓ | 按文档，未验证 |
| 腾讯元器 | — | — | — | — | — | ✓ | 按文档，未验证 |
| 火山方舟 | — | — | — | — | — | ✓ | 按文档，未验证（Viking 需 AK/SK） |
| 讯飞星火 | — | — | — | — | — | ✓ | 按文档，未验证 |
| OpenAI 兼容网关 | — | — | — | — | — | ✓ | 可配置 |
| generic | 按 profile | 按 profile | 按 profile | 按 profile | 按 profile | ✓ | 由用户 profile 决定 |

\* Dify 高质量索引建库需要 `embedding_model_provider` + `embedding_model`；否则请先在 Dify 控制台建库再选择。

Coze 不开放分片查询，因此无法把远端 chunk 落成本地 Chunk；该路径下评测只能依赖对话返回的
`knowledge` 消息作为上下文，检索类指标会缺 target。

### 4.1 RAGFlow 版本契约与实测记录

以官方 tag `v1.0.0-rc2` 的 Go 源码为准（`internal/handler`、`internal/service`），
与 0.x 的差异已经写进 `backend/app/services/api_ingest/ragflow.py` 顶部注释：

| 动作 | v1.0 | 0.x（连接器自动回退） |
| --- | --- | --- |
| 建库字段 | `name` / `parse_type`（**int**，1=BuiltIn）/ `parser_id` / `permission` / `language` / `embedding_model` / `parser_config`；**不接受 `description`** | `chunk_method`、允许 `description` |
| 触发解析 | `POST /api/v1/documents/ingest`，body `{"doc_ids": [...], "run": "1"}`。`run` 是 TaskStatus 枚举字符串（1=Running，3=Cancel），**传 `"RUNNING"` 不报错但会被忽略，文档永远 pending** | `POST /datasets/{kb}/chunks`，body `{"document_ids": [...]}` |
| 文档状态字段 | `ingestion_status`：UNSTART/CREATED/SCHEDULED/RUNNING/STOPPING/COMPLETED/FAILED/STOPPED | `run`：UNSTART/RUNNING/DONE/FAIL/CANCEL |
| 问答 | `POST /api/v1/chat/completions`，body 带 `chat_id` / `question` / `stream` / 可选 `llm_id`；回答在 `data.answer`，召回在 `data.reference.chunks` | `POST /chats/{id}/completions`，`chat_id` 在路径 |
| 响应信封 | `{code, data, message}`，`code != 0` 视为失败 | 同左 |

回退策略：建库报字段类错误（`Extra inputs are not permitted` / `cannot unmarshal` /
提到 `parse_type`、`chunk_method`）时按 0.x 形状重发一次；解析接口或问答接口 404 时
改走 0.x 路径。其余错误（鉴权、网络、5xx）直接上抛，不做猜测重试。

实测记录（本机 Docker 部署，`v1.0.0-rc2`，2026-10-29）：

- 通过：注册 / 登录（token 在响应 **Authorization 头**）、`/system/keys` 建 Key、
  列库、建库（v1.0 字段）、multipart 上传、`/documents/ingest` 触发解析
  （`run:"1"`，状态 running→done，progress 0→0.8→1.0）、拉分片、建会话助手、
  `/chat/completions` 问答并取回 `reference.chunks`。
- 实测纠错 1：建库带 `description` 被拒（`code:101 Extra inputs are not permitted`），
  `parse_type` 必须是整数。
- 实测纠错 2：`run` 传 `"RUNNING"` 时接口返回 success 但任务不启动，改成 `"1"` 后才真正解析。
- 实测纠错 3：`POST /chats/{id}/completions` 在 v1.0 已不存在（404），改为
  `POST /chat/completions` + body `chat_id`。
- 环境限制（已解决）：共享 LLM/embedding 网关一度过载/欠费/EOL（503、410、余额不足），
  真实回答当时验证不了；网关恢复后已用 **bge-m3 向量检索 + Qwen3.8-Flash-Next**
  实测问答：提问「一线城市住宿报销上限是多少？」返回
  「每人每晚不超过 600 元」，`reference.chunks` 命中对应分片。
- 复现脚本：`.local/e2e_ragflow.py`（不提交，内含本地 Key 读取）。

### 4.2 PageIndex / LLM Wiki 契约（按文档实现，未实测）

#### PageIndex（VectifyAI）

无向量库、无 chunk：每篇文档由 LLM 生成**层级树索引**，检索时让模型在树上推理。
云端 API 与本地 SDK 是两条路：

| 能力 | 形态 |
| --- | --- |
| 本地模式 | `pip install pageindex`，只有 Python SDK，**没有 HTTP 服务**；要接 jq-eval 需自建薄服务 |
| 云端 API | `https://api.pageindex.ai`，真实 HTTP 接口，连接器走这条 |
| 鉴权 | 请求头 `api_key: <key>`，**不是** `Authorization: Bearer` |
| 上传 | `POST /doc/`（multipart `file`，仅 PDF）→ `{doc_id}`；上传即自动建树，无“触发解析” |
| 状态 | `GET /doc/{id}/` 返回 `status`：`processing` / `completed`；`GET /docs` 列文档 |
| 分片 | `GET /doc/{id}/?type=tree` 的节点（`node_id` / `page_index` / `text`）落成本地 Chunk |
| 问答 | `POST /chat/completions`，OpenAI 形状，可带 `doc_id` 限定文档；引用在 `message.citations` |

连接器把账号下全部文档视为一个虚拟库（`pageindex:account`），因为 PageIndex 本身没有知识库概念。

#### LLM Wiki（nashsu/llm_wiki）

Karpathy「LLM Wiki」模式的开源桌面实现：文档 → 结构化的互链 wiki 页，而不是每次现查向量。
桌面应用内置**本地 HTTP API**（`http://127.0.0.1:19828/api/v1`，Bearer token 在
Settings → API + MCP 生成，默认只监听本机）：

| 动作 | 接口 |
| --- | --- |
| 列项目（=知识库） | `GET /projects` |
| 写入页面 | `POST /projects/{id}/pages/write` `{path, content, allowOverwrite}` |
| 建向量 | `POST /projects/{id}/pages/embed` `{path, force}` |
| 列页面 | `GET /projects/{id}/files?root=wiki&recursive=true` |
| 问答 | `POST /projects/{id}/chat` `{message, sessionId?, tools:{wiki,web,anytxt}}` → `message.content` + `references` |

限制（连接器能力里已声明）：

- 没有原始文件上传接口，PDF/DOCX 的解析编译只能在桌面端 Sources 做；API 路径是把文本
  写进 `wiki/imports/*.md` 再 embed，这是官方给外部 agent 的写入入口。
- 没有分片列表接口（只有按 query 的 hybrid search），因此 `list_chunks=False`，
  评测上下文取 chat 返回的 `references.snippet`，检索类指标的 target 需要另行设计。
- 桌面应用必须在本机运行，否则 `127.0.0.1:19828` 直接连接失败。

两者均未在本地部署验证：PageIndex 云端需要 key，LLM Wiki 需要桌面应用常驻。

### 4.3 >1k star 开源方案覆盖口径（2026-10-28 快照）

「覆盖」不等于「每个仓库都写一个连接器」：RAG 生态里大量项目是框架/库、向量库、
解析器或聊天 UI，它们没有「独立部署 + 知识库 HTTP API」这个被测对象。为避免
「没接 = 漏了」的误解，清单分四类，机器可读版本在 `GET /ingest-catalog`：

| 类别 | 数量 | 含义 |
| --- | --- | --- |
| native | 15 | 原生连接器，含建库/上传/状态/分片/问答中的全部或大部分能力 |
| profile | 3 | 通过通用 profile 接入（Flowise / DB-GPT / Langflow），默认只接问答 |
| gateway | 3 | API 契约不稳定或管理接口需管理员权限（Quivr / Onyx / BISHENG），建议先自建网关 |
| excluded | 10 | 框架/库/向量库/聊天 UI/已归档且无稳定 API，明确不计入 |

纳入规则：

1. 面向最终用户的 RAG / 知识库应用，且提供可调用的 HTTP API；
2. 纯框架/库（LangChain、LlamaIndex、Haystack、GraphRAG、RAG-Anything、MiniRAG）、
   向量数据库（Milvus/Qdrant/Weaviate/Chroma）、解析器（Docling/MinerU）、
   评测库（Ragas/DeepEval）、记忆层（Mem0/Cognee/Zep/Letta）不计入；
3. 纯聊天 UI（LibreChat/LobeChat）如果没有稳定的知识库管理 API，也不计入；
4. 已归档仓库仍然列出：能跑就接，不能跑就写明原因，不能静默消失。

覆盖清单中的 `verified=False` 表示「按官方 API/源码实现、契约测试通过，但未在本机
实机联调」。RAGFlow 是唯一已完成本地全链路实测的系统；新增连接器不要因为
离线测试通过就改成已验证。

## 5. 官方文档

- RAGFlow HTTP API：https://ragflow.io/docs/dev/http_api_reference
- RAGFlow Python SDK：https://github.com/infiniflow/ragflow/tree/main/sdk/python/ragflow_sdk
- Dify 知识库 API：https://docs.dify.ai/guides/knowledge-base/knowledge-base-api
- Dify 应用 API：https://docs.dify.ai/guides/application-publishing/developing-with-apis
- FastGPT Dataset API：https://doc.fastgpt.io/en/openapi/dataset
- FastGPT Chat API：https://doc.fastgpt.io/en/openapi/chat
- Coze 创建知识库：https://docs.coze.cn/developer_guides_create_dataset
- Coze 创建知识库文件：https://docs.coze.cn/developer_guides_create_knowledge_files
- Coze 对话 v3：https://docs.coze.cn/developer_guides_chat_v3
- PageIndex API Reference：https://docs.pageindex.ai/api-reference
- PageIndex 开源仓库：https://github.com/VectifyAI/PageIndex
- LLM Wiki 本地 HTTP API：https://github.com/nashsu/llm_wiki#local-http-api--mcp-server--ai-agent-skill
- LLM Wiki 配套 skill / API 客户端：https://github.com/nashsu/llm_wiki_skill
- Karpathy LLM Wiki 模式（原始 gist）：https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- AnythingLLM API：https://docs.anythingllm.com/
- Open WebUI API / 源码：https://docs.openwebui.com/、https://github.com/open-webui/open-webui/tree/main/backend/open_webui/routers
- MaxKB API：https://docs.fit2cloud.com/maxkb/
- LightRAG Server：https://github.com/HKUDS/LightRAG
- Langchain-Chatchat API Server：https://github.com/chatchat-space/Langchain-Chatchat
- QAnything API：https://github.com/netease-youdao/QAnything
- PrivateGPT API：https://docs.privategpt.dev/
- DocsGPT API：https://docs.docsgpt.cloud/
- R2R API：https://r2r-docs.sciphi.ai/
- Khoj API：https://docs.khoj.dev/
- Flowise API：https://docs.flowiseai.com/
- DB-GPT：https://docs.dbgpt.cn/
- Langflow API：https://docs.langflow.org/
- 百度千帆：https://cloud.baidu.com/doc/qianfan-api/s/tm7wzq8ek
- 阿里云百炼知识库：https://help.aliyun.com/zh/model-studio/rag-knowledge-base-api-guide
- 腾讯元器：https://yuanqi.tencent.com/guide/publish-agent-api-documentation
- 腾讯 LKE：https://cloud.tencent.com/document/product/1759/105561
- 火山方舟：https://www.volcengine.com/docs/82379
- 讯飞星火 HTTP：https://www.xfyun.cn/doc/spark/HTTP%E8%B0%83%E7%94%A8%E6%96%87%E6%A1%A3.html

## 6. 测试

离线契约测试用 `httpx.MockTransport` 扮演各系统，验证请求形状与响应解析：

```bash
cd backend
.venv/Scripts/python.exe -m pytest tests/test_api_ingest.py -q
```

覆盖：RAGFlow 建库/上传/触发解析/轮询/分片/问答（含 v1.0 与 0.x 双形状回退）、
Dify 双 key 与 401 提示、FastGPT `{code,data}` 信封与 collection 状态、
Coze 建库/上传/非流式轮询、通用 profile 覆盖；
AnythingLLM / Open WebUI / MaxKB / LightRAG / Langchain-Chatchat / QAnything /
PrivateGPT / DocsGPT / R2R / Khoj 的请求形状与响应解析；
以及「注册表里的每个已接入类型都能在 >1k star 清单里找到 star/repo/说明」。

实机联调记录应写入本文档「验证状态」列，未跑通前不要改成已验证。
