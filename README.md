# 智能评估系统 (JQ-Eval)

RAG/LLM系统智能评估平台，支持多系统适配、指标市场、数据同步、根因分析。

## 快速开始

### 1. 启动中间件

```bash
# 启动所有中间件
docker-compose up -d

# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f milvus

# 停止
docker-compose down
```

### 2. 验证服务

```bash
# 验证 PostgreSQL
docker exec -it jqeval-postgres psql -U jqeval -d jqeval -c "SELECT 1"

# 验证 Redis
docker exec -it jqeval-redis redis-cli -a jqeval123 ping

# 验证 Milvus (等待启动完成，约30秒)
curl http://localhost:9091/healthz
```

### 3. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 根据需要修改配置
```

## 中间件连接信息

| 服务 | 地址 | 用户名 | 密码 |
|-----|------|--------|------|
| PostgreSQL | localhost:5432 | jqeval | jqeval123 |
| Redis | localhost:6379 | - | jqeval123 |
| MinIO API | localhost:9000 | minioadmin | minioadmin123 |
| MinIO Console | http://localhost:9001 | minioadmin | minioadmin123 |
| Milvus | localhost:19530 | - | - |

## 服务端口说明

| 服务 | 端口 | 说明 |
|-----|------|------|
| PostgreSQL | 5432 | 数据库 |
| Redis | 6379 | 缓存/队列 |
| MinIO API | 9000 | 对象存储API |
| MinIO Console | 9001 | MinIO管理界面 |
| Milvus gRPC | 19530 | 向量数据库gRPC |
| Milvus Health | 9091 | 健康检查 |
| Milvus MinIO API | 9002 | Milvus内部MinIO |
| Milvus MinIO Console | 9003 | Milvus内部MinIO管理 |

## 项目结构

```
jq-eval/
├── backend/                 # 后端代码
│   ├── app/
│   │   ├── api/v1/         # API路由（24个路由模块，219个端点）
│   │   ├── core/           # 配置/数据库/Celery
│   │   ├── models/         # SQLAlchemy 模型（46张业务表，跨方言类型层）
│   │   ├── tasks/          # Celery 异步任务（评估/生成/解析/压测/爬虫）
│   │   └── services/       # 业务服务（adapters/metrics/llm/graph/training_data/vibe_agent...）
│   └── requirements.txt
├── frontend/                # React 18 + Vite 前端
│   └── src/
│       ├── pages/          # 22个页面（懒加载路由）
│       ├── api/            # 接口封装（axios 拦截器统一错误处理）
│       ├── components/     # 通用组件
│       ├── hooks/          # 轮询/WebSocket 复用钩子
│       └── types/          # TS 类型定义
├── docs/API.md             # API 文档
├── docker-compose.yml      # 中间件编排
├── .env.example            # 环境变量模板
└── 需求说明.md              # 设计文档
```

## 架构亮点（面试重点）

- **调用与评估分离的两段式设计**：先批量调用RAG/模型产出结果（invocation_results），评估任务可复用历史调用结果换指标重评，避免重复调用大模型浪费Token
- **OpenAI/Anthropic 双协议代理**：入站请求统一转内部表示（protocol_converter），出站按目标模型协议转换，SSE流式透传，映射密钥鉴权（hmac比对），调用日志记录请求/响应/时延
- **密钥静态加密**：上游 API 密钥与对外映射密钥 Fernet 加密落库，EncryptedText TypeDecorator 读写透明、历史明文渐进迁移，密钥轮换失败不留错误凭据
- **指标插件化**：所有指标实现 BaseMetric 接口并注册 REGISTRY，前端"指标市场"动态勾选组合，检索指标与生成指标按评估阶段分组
- **多源数据同步**：Dify/FastGPT/n8n/自定义库 四种同步适配器，字段映射可配置，同步前先探测连接/预览Schema，快照机制保证历史可追溯
- **Celery 工程化**：NullPool 规避 asyncpg 跨 event loop 连接崩溃；任务失败统一 rollback+重取+标记 FAILED；PROGRESS 状态实时上报；任务超时与 acks_late 配置
- **前端工程化**：路由级代码分割 + vendor按依赖分包（echarts/antd/mermaid独立chunk）；轮询串行化防请求堆积；WebSocket 卸载防泄漏；统一错误拦截器

## 功能特性

- **RAG系统适配**: 支持Dify、Coze、FastGPT、n8n、自定义系统
- **数据同步**: 从主流RAG系统数据库同步分片、QA数据
- **指标市场**: 用户可勾选组合评估指标
- **评估引擎**: Ragas + EvalScope + 自研指标
- **根因分析**: 评估结果分析与调参建议
- **快照机制**: 历史数据冻结，保证可追溯
- **向量检索**: Milvus高性能向量检索
- **调用与评估解耦**: 调用批次(Invocation)与评估(Evaluation)分离，支持复用调用结果重评（reuse_invocation），同一批对话可换指标/换模型反复评估
- **模型调用映射代理**: 对外暴露 OpenAI/Anthropic 协议端点（/v1/chat/completions、/v1/messages），按映射转发到目标模型，协议自动互转，调用日志全量落库，支持流式
- **大模型压测**: QPS上限探测与响应时间分布两种模式，直连模型或RAG系统，输出P50/P90/P99延迟、错误分类汇总与失败样本
- **文档解析**: 集成 minerU 官方API批量解析 PDF/图片/Office 文档，解析产物入库支持二次评估
- **训练数据质量评估**: 面向 LLM/Embedding/Reranker/DPO/奖励模型 等训练数据的专项指标引擎，输出质量标签与改进建议
- **Prompt管理**: 提示词版本管理、A/B 对比与自动优化
- **标注纠错闭环**: 评估结果可转标注任务，LLM辅助生成纠错建议
- **VibeAgent**: 对话式生成 RAG 工作流（自然语言→Mermaid 流程图→可运行代码）
- **知识图谱构建**: LightRAG 实体/关系抽取，构建知识图谱

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | React 18 + TypeScript + Ant Design 5 + ECharts + Vite |
| 后端 | Python 3.10+ / FastAPI (async) / SQLAlchemy 2 (asyncpg) |
| 异步任务 | Celery + Redis（Beat 定时调度，任务进度实时上报） |
| 存储 | PostgreSQL (JSONB) / Milvus (向量) / MinIO (对象) / Redis |
| 评估 | Ragas / EvalScope / 自研指标引擎（检索与生成阶段解耦） |
| LLM接入 | LangChain（统一超时/重试），多模型映射代理 |

## 常用命令

```bash
# 启动服务
docker-compose up -d

# 停止服务
docker-compose down

# 停止并删除数据卷
docker-compose down -v

# 查看服务日志
docker-compose logs -f [service_name]

# 重启单个服务
docker-compose restart milvus
```

## 本地启动指南（开发环境）

> 以下命令在 Windows（PowerShell）下验证过，Linux/Mac 差异之处已标注。

### 0. 前置要求

- Python 3.10+（开发与测试验证环境为 3.10，3.11/3.12 兼容）
- Node.js 18+、pnpm（`npm i -g pnpm`）
- Docker（用于中间件）

### 1. 配置环境变量

```bash
# 在项目根目录执行（首次）
cp .env.example .env
```

`.env` 已默认指向 localhost 的中间件，如需修改连接信息直接编辑该文件。

### 2. 启动中间件

```bash
docker-compose up -d
# 验证
curl http://localhost:9091/healthz   # Milvus
```

### 3. 启动后端（端口 8000）

```powershell
cd backend

# 首次：创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 后续启动
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Linux/Mac：

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

验证：

- 健康检查：http://localhost:8000/health → `{"status":"healthy",...}`
- API 文档：http://localhost:8000/docs

### 4. 启动前端（端口 3000，新开终端）

```powershell
cd frontend

# 首次：安装依赖
pnpm install

# 后续启动
pnpm dev
```

访问 http://localhost:3000，Vite 已将 `/api` 代理到后端 8000 端口，无需额外配置跨域。

### 5. 启动 Celery Worker（异步任务必需，新开终端）

评估任务、测试集生成、数据同步、爬虫等长耗时操作都走 Celery，不启动则页面任务会一直停留在等待状态。

```powershell
cd backend
.venv\Scripts\Activate.ps1
# Windows 必须加 --pool=solo
celery -A app.core.celery_app worker --pool=solo --loglevel=info
```

Linux/Mac：

```bash
cd backend
source .venv/bin/activate
celery -A app.core.celery_app worker --loglevel=info
```

### 6. 启动 Celery Beat（可选，定时任务调度）

只有定时抓取 RSS 新闻源等周期任务需要，按需启动：

```powershell
cd backend
.venv\Scripts\Activate.ps1
celery -A app.core.celery_app beat --loglevel=info
```

### 启动检查清单

| 检查项 | 命令/地址 | 预期 |
|-------|----------|------|
| Milvus | `curl http://localhost:9091/healthz` | OK |
| 后端 | http://localhost:8000/health | `{"status":"healthy"}` |
| 前端 | http://localhost:3000 | 页面正常渲染 |
| 前端代理 | http://localhost:3000/api/v1/health | 返回后端健康 JSON |

### 常见问题

- **后端启动报 `SyntaxError` / 接口 500**：确认在项目根目录创建了 `.env`，且中间件容器已启动。
- **前端依赖安装后 vite 启动报 esbuild 错误**：pnpm 可能拦截了构建脚本，执行 `pnpm approve-builds` 勾选 esbuild 后重装。
- **评估任务一直 pending**：Celery Worker 未启动，见第 5 步。
- **端口占用**：后端默认 8000、前端默认 3000，可在启动命令或 `frontend/vite.config.ts` 中调整。

## 测试

```bash
cd backend
source venv/bin/activate   # Windows: .env\Scripts\Activate.ps1
pytest                     # 69 个用例，SQLite 内存库，无需任何中间件，约 7s
```

测试体系说明：模型层通过 `app/core/db_types.py` 的跨方言类型（UUIDType/JSONType/ArrayType）
在 PostgreSQL（生产）与 SQLite（测试）间共享同一套定义；回归测试覆盖路由注册顺序
（静态路由防 `/{uuid}` 遮蔽）、任务派发状态机（running/回滚）、协作式取消、分页稳定性、
数据导入健壮性与子资源归属校验。

## 开发

- 设计文档：[需求说明.md](./需求说明.md)
- API 接口文档：[docs/API.md](./docs/API.md)（核心接口；全部 219 个端点可启动后端后访问 http://localhost:8000/docs 查看交互式文档）
- 检索与分析思路：[检索分析.md](./检索分析.md)
