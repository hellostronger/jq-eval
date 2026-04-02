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

## 开发

详见 [需求说明.md](./需求说明.md)