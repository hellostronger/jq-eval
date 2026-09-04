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
│   │   ├── api/            # API路由
│   │   ├── core/           # 核心配置
│   │   ├── models/         # 数据库模型
│   │   ├── schemas/        # Pydantic Schema
│   │   └── services/       # 业务服务
│   └── migrations/         # 数据库迁移
├── docker-compose.yml      # 中间件编排
├── .env.example            # 环境变量模板
└── 需求说明.md              # 设计文档
```

## 功能特性

- **RAG系统适配**: 支持Dify、Coze、FastGPT、n8n、自定义系统
- **数据同步**: 从主流RAG系统数据库同步分片、QA数据
- **指标市场**: 用户可勾选组合评估指标
- **评估引擎**: Ragas + EvalScope + 自研指标
- **根因分析**: 评估结果分析与调参建议
- **快照机制**: 历史数据冻结，保证可追溯
- **向量检索**: Milvus高性能向量检索

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

- Python 3.11+（开发时使用 3.12）
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

## 开发

详见 [需求说明.md](./需求说明.md)