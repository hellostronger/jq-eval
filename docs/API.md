# JQ-Eval API 接口文档

> RAG/LLM系统智能评估平台 API v1
> Base URL: `/api/v1`

---

## 目录

1. [健康检查](#1-健康检查)
2. [模型管理](#2-模型管理)
3. [RAG系统管理](#3-rag系统管理)
4. [数据集管理](#4-数据集管理)
5. [评估任务](#5-评估任务)
6. [指标市场](#6-指标市场)
7. [数据源与同步](#7-数据源与同步)
8. [文件存储](#8-文件存储)
9. [图谱构建](#9-图谱构建)

---

## 1. 健康检查

### 1.1 基础健康检查

```
GET /health
```

**响应示例：**
```json
{
  "status": "healthy",
  "app": "JQ-Eval",
  "version": "1.0.0"
}
```

### 1.2 服务就绪检查

```
GET /api/v1/health/ready
```

检查所有中间件连接状态（PostgreSQL、Redis、Milvus、MinIO）。

**响应示例：**
```json
{
  "status": "ready",
  "services": {
    "database": {"status": "healthy", "type": "PostgreSQL"},
    "redis": {"status": "healthy"},
    "milvus": {"status": "healthy"},
    "minio": {"status": "healthy"}
  }
}
```

---

## 2. 模型管理

> 路径前缀: `/api/v1/models`

### 2.1 创建模型配置

```
POST /api/v1/models
```

**请求体：**
```json
{
  "name": "gpt-4o-mini",
  "model_type": "llm",           // llm | embedding | reranker
  "provider": "openai",
  "endpoint": "https://api.openai.com/v1",
  "api_key": "sk-xxx",
  "params": {
    "max_tokens": 4000,
    "temperature": 0.1
  },
  "is_default": true,
  "dimension": 1536,             // embedding模型维度
  "max_input_length": 8192
}
```

**响应：**
```json
{
  "id": "uuid",
  "name": "gpt-4o-mini",
  "model_type": "llm",
  "provider": "openai",
  "endpoint": "https://api.openai.com/v1",
  "params": {...},
  "is_default": true,
  "status": "active",
  "dimension": 1536,
  "max_input_length": 8192
}
```

### 2.2 获取模型列表

```
GET /api/v1/models?model_type=llm
```

**参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| model_type | string | 否 | 模型类型过滤：llm/embedding/reranker |

### 2.3 获取模型详情

```
GET /api/v1/models/{model_id}
```

### 2.4 更新模型配置

```
PUT /api/v1/models/{model_id}
```

**请求体：** 同创建模型

### 2.5 删除模型

```
DELETE /api/v1/models/{model_id}
```

**响应：**
```json
{"message": "删除成功"}
```

### 2.6 测试模型连接

```
POST /api/v1/models/{model_id}/test
```

**请求体：**
```json
{
  "test_prompt": "Hello, this is a test."
}
```

**响应：**
```json
{
  "success": true,
  "message": "模型连接测试成功",
  "model_id": "uuid"
}
```

---

## 3. RAG系统管理

> 路径前缀: `/api/v1/rag-systems`

### 3.1 获取支持的RAG系统类型

```
GET /api/v1/rag-systems/types
```

**响应示例：**
```json
[
  {
    "type_code": "dify",
    "display_name": "Dify",
    "description": "Dify知识库系统",
    "connection_schema": {...},
    "capabilities": ["query", "upload", "delete"],
    "api_doc_url": "https://docs.dify.ai"
  }
]
```

### 3.2 创建RAG系统配置

```
POST /api/v1/rag-systems
```

**请求体：**
```json
{
  "name": "我的Dify知识库",
  "system_type": "dify",
  "description": "生产环境知识库",
  "connection_config": {
    "api_url": "https://api.dify.ai/v1",
    "api_key": "app-xxx",
    "dataset_id": "xxx"
  },
  "llm_config": {
    "model": "gpt-4",
    "temperature": 0.7
  },
  "retrieval_config": {
    "top_k": 5,
    "score_threshold": 0.5
  }
}
```

### 3.3 获取RAG系统列表

```
GET /api/v1/rag-systems?system_type=dify
```

**参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| system_type | string | 否 | 系统类型过滤 |

### 3.4 获取RAG系统详情

```
GET /api/v1/rag-systems/{system_id}
```

### 3.5 更新RAG系统配置

```
PUT /api/v1/rag-systems/{system_id}
```

### 3.6 删除RAG系统

```
DELETE /api/v1/rag-systems/{system_id}
```

### 3.7 查询RAG系统

```
POST /api/v1/rag-systems/{system_id}/query
```

**请求体：**
```json
{
  "question": "什么是知识图谱?",
  "conversation_id": "optional-session-id",
  "contexts": ["可选的上下文列表"]
}
```

**响应：**
```json
{
  "answer": "知识图谱是一种结构化的知识表示...",
  "contexts": [" retrieved doc 1", "retrieved doc 2"],
  "response_time": 1.23,
  "success": true,
  "error": null
}
```

### 3.8 RAG系统健康检查

```
POST /api/v1/rag-systems/{system_id}/health
```

**响应：**
```json
{
  "system_id": "uuid",
  "health_status": "healthy",
  "checked_at": "2024-01-15T10:30:00Z"
}
```

---

## 4. 数据集管理

> 路径前缀: `/api/v1/datasets`

### 4.1 创建数据集

```
POST /api/v1/datasets
```

**请求体：**
```json
{
  "name": "测试数据集",
  "description": "用于评估的测试数据",
  "source_type": "manual",
  "source_url": null
}
```

**响应：**
```json
{
  "id": "uuid",
  "name": "测试数据集",
  "description": "用于评估的测试数据",
  "source_type": "manual",
  "record_count": 0,
  "has_ground_truth": false,
  "has_contexts": false,
  "status": "active"
}
```

### 4.2 获取数据集列表

```
GET /api/v1/datasets?status=active
```

### 4.3 获取数据集详情

```
GET /api/v1/datasets/{dataset_id}
```

### 4.4 删除数据集

```
DELETE /api/v1/datasets/{dataset_id}
```

### 4.5 获取数据集QA记录

```
GET /api/v1/datasets/{dataset_id}/records?skip=0&limit=100
```

**响应：**
```json
[
  {
    "id": "uuid",
    "question": "什么是RAG?",
    "answer": "RAG是检索增强生成...",
    "ground_truth": "RAG结合了检索和生成...",
    "question_type": "factual",
    "difficulty": "medium"
  }
]
```

### 4.6 添加QA记录

```
POST /api/v1/datasets/{dataset_id}/records
```

**请求体：**
```json
{
  "question": "什么是知识图谱?",
  "answer": "知识图谱是...",
  "ground_truth": "标准答案...",
  "contexts": ["context1", "context2"],
  "question_type": "factual",
  "difficulty": "medium",
  "metadata": {}
}
```

### 4.7 导入数据文件

```
POST /api/v1/datasets/{dataset_id}/import
```

**请求：** multipart/form-data，上传文件（JSON/JSONL/CSV）

**响应：**
```json
{
  "message": "数据导入任务已创建",
  "filename": "dataset.json",
  "dataset_id": "uuid"
}
```

### 4.8 验证数据集完整性

```
GET /api/v1/datasets/{dataset_id}/validate
```

**响应：**
```json
{
  "dataset_id": "uuid",
  "total_records": 100,
  "with_ground_truth": 80,
  "completeness": {
    "has_ground_truth": true,
    "has_contexts": true
  }
}
```

---

## 5. 评估任务

> 路径前缀: `/api/v1/evaluations`

### 5.1 创建评估任务

```
POST /api/v1/evaluations
```

**请求体：**
```json
{
  "name": "Dify系统评估",
  "dataset_id": "uuid",
  "config": {
    "batch_size": 10,
    "parallel_workers": 3
  },
  "metrics": ["faithfulness", "answer_relevance", "context_precision"],
  "rag_system_ids": ["uuid1", "uuid2"]
}
```

**响应：**
```json
{
  "id": "uuid",
  "name": "Dify系统评估",
  "dataset_id": "uuid",
  "status": "pending",
  "progress": 0,
  "config": {...},
  "metrics": [...]
}
```

### 5.2 获取评估任务列表

```
GET /api/v1/evaluations?status=completed&dataset_id=uuid
```

**参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| status | string | 否 | 状态过滤：pending/running/completed/failed |
| dataset_id | uuid | 否 | 数据集ID过滤 |

### 5.3 获取评估任务详情

```
GET /api/v1/evaluations/{eval_id}
```

### 5.4 删除评估任务

```
DELETE /api/v1/evaluations/{eval_id}
```

### 5.5 执行评估任务

```
POST /api/v1/evaluations/{eval_id}/run
```

**响应：**
```json
{
  "message": "评估任务已启动",
  "eval_id": "uuid"
}
```

### 5.6 获取评估任务状态

```
GET /api/v1/evaluations/{eval_id}/status
```

**响应：**
```json
{
  "eval_id": "uuid",
  "status": "running",
  "progress": 45,
  "error": null
}
```

### 5.7 获取评估结果

```
GET /api/v1/evaluations/{eval_id}/results?skip=0&limit=100
```

**响应：**
```json
{
  "eval_id": "uuid",
  "summary": {
    "faithfulness": {"mean": 0.85, "std": 0.12},
    "answer_relevance": {"mean": 0.78, "std": 0.15}
  },
  "results": [
    {
      "id": "uuid",
      "qa_record_id": "uuid",
      "scores": {
        "faithfulness": 0.9,
        "answer_relevance": 0.8
      }
    }
  ]
}
```

### 5.8 获取根因分析

```
GET /api/v1/evaluations/{eval_id}/analysis
```

**响应：**
```json
{
  "eval_id": "uuid",
  "analysis": {
    "retrieval_analysis": {...},
    "generation_analysis": {...},
    "recommendations": [...]
  }
}
```

### 5.9 导出评估报告

```
GET /api/v1/evaluations/{eval_id}/export?format=json
```

**参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| format | string | 否 | 导出格式：json/csv/pdf |

---

## 6. 指标市场

> 路径前缀: `/api/v1/metrics`

### 6.1 浏览指标列表

```
GET /api/v1/metrics?category=retrieval&framework=ragas&search=faith
```

**参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| category | string | 否 | 分类：retrieval/generation/quality/performance/custom |
| framework | string | 否 | 框架：ragas/evalscope/custom |
| search | string | 否 | 搜索关键词 |

**响应：**
```json
[
  {
    "id": "uuid",
    "name": "faithfulness",
    "display_name": "忠实度",
    "display_name_en": "Faithfulness",
    "description": "评估回答是否忠实于检索上下文",
    "category": "generation",
    "framework": "ragas",
    "requires_llm": true,
    "requires_embedding": false,
    "requires_ground_truth": false,
    "requires_contexts": true,
    "usage_count": 156,
    "is_builtin": true,
    "tags": ["quality", "generation"]
  }
]
```

### 6.2 获取指标分类

```
GET /api/v1/metrics/categories
```

**响应：**
```json
["retrieval", "generation", "quality", "performance", "custom"]
```

### 6.3 获取指标详情

```
GET /api/v1/metrics/{metric_id}
```

### 6.4 创建自定义指标

```
POST /api/v1/metrics
```

**请求体：**
```json
{
  "name": "my_custom_metric",
  "display_name": "自定义指标",
  "display_name_en": "My Custom Metric",
  "description": "描述",
  "category": "custom",
  "framework": null,
  "params_schema": {
    "threshold": {"type": "float", "default": 0.5}
  },
  "default_params": {"threshold": 0.5},
  "requires_llm": false,
  "requires_embedding": false,
  "requires_ground_truth": true,
  "requires_contexts": false,
  "range_min": 0.0,
  "range_max": 1.0,
  "higher_is_better": true,
  "tags": ["custom", "business"]
}
```

### 6.5 对指标评分

```
POST /api/v1/metrics/{metric_id}/rate?rating=5
```

**参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| rating | int | 是 | 评分（1-5） |

---

## 7. 数据源与同步

> 路径前缀: `/api/v1/data-sources`

### 7.1 获取支持的系统列表

```
GET /api/v1/data-sources/supported-systems
```

**响应：**
```json
[
  {
    "system_type": "dify",
    "display_name": "Dify",
    "db_type": "postgresql",
    "sync_targets": ["document_segments", "messages"],
    "description": "同步Dify知识库分片和对话消息"
  },
  {
    "system_type": "fastgpt",
    "display_name": "FastGPT",
    "db_type": "mongodb",
    "sync_targets": ["kb_data", "chat"],
    "description": "同步FastGPT知识库数据和对话记录"
  },
  {
    "system_type": "coze",
    "display_name": "Coze",
    "db_type": "postgresql",
    "sync_targets": ["bot_data", "conversations"],
    "description": "同步Coze机器人数据和对话"
  },
  {
    "system_type": "lightrag",
    "display_name": "LightRAG",
    "db_type": "sqlite",
    "sync_targets": ["graph_data", "documents"],
    "description": "同步LightRAG图谱数据"
  }
]
```

### 7.2 创建数据源

```
POST /api/v1/data-sources
```

**请求体：**
```json
{
  "name": "Dify生产库",
  "source_type": "database",
  "system_type": "dify",
  "connection_config": {
    "db_type": "postgresql",
    "db_url": "postgresql://host:5432/dify",
    "password": "xxx",
    "version": "1.0"
  },
  "sync_config": {
    "auto_sync": true,
    "sync_interval": 3600
  }
}
```

**响应：**
```json
{
  "id": "uuid",
  "name": "Dify生产库",
  "source_type": "database",
  "system_type": "dify",
  "status": "active",
  "sync_status": null,
  "total_synced": 0
}
```

### 7.3 获取数据源列表

```
GET /api/v1/data-sources?source_type=database
```

### 7.4 获取数据源详情

```
GET /api/v1/data-sources/{source_id}
```

### 7.5 删除数据源

```
DELETE /api/v1/data-sources/{source_id}
```

### 7.6 测试数据源连接

```
POST /api/v1/data-sources/{source_id}/test-connection
```

**响应：**
```json
{
  "success": true,
  "message": "连接测试成功",
  "source_id": "uuid"
}
```

### 7.7 获取数据源表列表

```
GET /api/v1/data-sources/{source_id}/tables
```

### 7.8 获取数据源Schema

```
GET /api/v1/data-sources/{source_id}/schema
```

### 7.9 预览表数据

```
GET /api/v1/data-sources/{source_id}/preview/{table}?limit=10
```

### 7.10 获取默认字段映射

```
GET /api/v1/data-sources/{source_id}/default-mappings
```

### 7.11 执行数据同步

```
POST /api/v1/data-sources/{source_id}/sync
```

**请求体：**
```json
{
  "dataset_id": "uuid",
  "tables": ["document_segments", "messages"],
  "mappings": {
    "document_segments": [
      {"source_field": "content", "target_field": "question"},
      {"source_field": "answer", "target_field": "answer"}
    ]
  },
  "incremental": false
}
```

**响应：**
```json
{
  "task_id": "uuid",
  "status": "pending",
  "message": "同步任务已创建"
}
```

### 7.12 获取同步任务列表

```
GET /api/v1/data-sources/{source_id}/sync-tasks
```

### 7.13 获取同步任务详情

```
GET /api/v1/data-sources/sync-tasks/{task_id}
```

**响应：**
```json
{
  "id": "uuid",
  "source_id": "uuid",
  "task_type": "full",
  "status": "completed",
  "progress": 100,
  "total_records": 1000,
  "synced_records": 1000,
  "failed_records": 0,
  "log": "..."
}
```

---

## 8. 文件存储

> 路径前缀: `/api/v1/files`

### 8.1 上传文件到指定bucket

```
POST /api/v1/files/upload/{bucket}
```

**请求：** multipart/form-data

**响应：**
```json
{
  "success": true,
  "bucket": "datasets",
  "object_name": "uuid_filename.json",
  "original_name": "dataset.json",
  "size": 1024,
  "url": null
}
```

### 8.2 上传数据集文件

```
POST /api/v1/files/upload-dataset
```

支持格式：CSV、JSON、Excel

### 8.3 获取下载URL

```
GET /api/v1/files/download/{bucket}/{object_name}?expires=3600
```

**响应：**
```json
{
  "url": "https://minio.example.com/...",
  "expires_in": 3600
}
```

### 8.4 获取文件信息

```
GET /api/v1/files/info/{bucket}/{object_name}
```

### 8.5 删除文件

```
DELETE /api/v1/files/delete/{bucket}/{object_name}
```

### 8.6 批量删除文件

```
POST /api/v1/files/delete-batch/{bucket}
```

**请求体：**
```json
["file1.json", "file2.json"]
```

### 8.7 列出bucket文件

```
GET /api/v1/files/list/{bucket}?prefix=&recursive=true
```

**响应：**
```json
[
  {
    "object_name": "datasets/file1.json",
    "size": 1024,
    "last_modified": "2024-01-15T10:00:00Z",
    "etag": "abc123",
    "content_type": "application/json"
  }
]
```

### 8.8 获取bucket统计

```
GET /api/v1/files/stats/{bucket}
```

**响应：**
```json
{
  "bucket": "datasets",
  "file_count": 50,
  "total_size": 5242880,
  "total_size_mb": 5.0
}
```

### 8.9 列出所有bucket

```
GET /api/v1/files/buckets
```

### 8.10 复制文件

```
POST /api/v1/files/copy
```

**请求体：**
```json
{
  "source_bucket": "datasets",
  "source_object": "file1.json",
  "dest_bucket": "backups",
  "dest_object": "backup_file1.json"
}
```

### 8.11 获取上传预签名URL

```
GET /api/v1/files/upload-url/{bucket}/{object_name}?expires=3600
```

用于客户端直传场景。

---

## 9. 图谱构建

> 路径前缀: `/api/v1/graph`

### 9.1 获取可用的图谱构建器

```
GET /api/v1/graph/builders
```

**响应：**
```json
[
  {
    "builder_type": "lightrag",
    "display_name": "LightRAG",
    "description": "基于LightRAG的知识图谱构建"
  }
]
```

### 9.2 获取构建器详情

```
GET /api/v1/graph/builders/{builder_type}
```

### 9.3 从文本块构建图谱

```
POST /api/v1/graph/build/chunks
```

**请求体：**
```json
{
  "chunks": ["文本块1", "文本块2", "文本块3"],
  "doc_id": "optional-doc-id",
  "builder_type": "lightrag",
  "entity_types": ["person", "organization", "location"],
  "language": "Chinese"
}
```

**响应：**
```json
{
  "success": true,
  "graph": {
    "entities": [
      {
        "name": "张三",
        "entity_type": "person",
        "description": "某公司的技术总监",
        "source_id": "chunk-0",
        "properties": {"source_ids": ["chunk-0"], "count": 1}
      }
    ],
    "relations": [
      {
        "source_entity": "张三",
        "target_entity": "某公司",
        "description": "就职于",
        "keywords": "就职,工作",
        "weight": 1.0,
        "source_id": "chunk-0"
      }
    ],
    "metadata": {
      "doc_id": "doc-1",
      "chunk_count": 3,
      "builder_type": "lightrag"
    }
  },
  "processing_time": 2.5,
  "chunk_count": 3,
  "entity_count": 5,
  "relation_count": 3
}
```

### 9.4 从完整文档构建图谱

```
POST /api/v1/graph/build/document
```

**请求体：**
```json
{
  "text": "完整的文档文本内容...",
  "doc_id": "doc-001",
  "builder_type": "lightrag",
  "entity_types": ["person", "organization", "concept"],
  "language": "Chinese",
  "chunk_size": 1200,
  "chunk_overlap": 100
}
```

### 9.5 从文件构建图谱

```
POST /api/v1/graph/build/file
```

**请求：** multipart/form-data，上传 .txt 或 .md 文件

**参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | file | 是 | 上传文件 |
| builder_type | string | 否 | 构建器类型，默认lightrag |
| entity_types | array | 否 | 自定义实体类型 |
| language | string | 否 | 输出语言：Chinese/English |
| chunk_size | int | 否 | 分块大小，默认1200 |
| chunk_overlap | int | 否 | 分块重叠，默认100 |

### 9.6 实体抽取

```
POST /api/v1/graph/extract/entities
```

**请求体：**
```json
{
  "text": "待抽取实体的文本",
  "entity_types": ["person", "organization"],
  "language": "Chinese",
  "builder_type": "lightrag"
}
```

**响应：**
```json
{
  "success": true,
  "entities": [...],
  "processing_time": 0.5
}
```

### 9.7 关系抽取

```
POST /api/v1/graph/extract/relations
```

**请求体：**
```json
{
  "text": "待抽取关系的文本",
  "entities": ["已知实体1", "已知实体2"],
  "language": "Chinese",
  "builder_type": "lightrag"
}
```

### 9.8 构建器健康检查

```
GET /api/v1/graph/health/{builder_type}
```

**响应：**
```json
{
  "builder_type": "lightrag",
  "status": "healthy"
}
```

---

## 通用错误响应

所有API在出错时返回统一格式：

```json
{
  "detail": "错误描述信息"
}
```

**常见HTTP状态码：**
| 状态码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 数据类型说明

### UUID格式
所有ID使用UUID格式，示例：`550e8400-e29b-41d4-a716-446655440000`

### 时间格式
时间使用ISO 8601格式：`2024-01-15T10:30:00Z`

### 状态枚举
- **模型状态**: active/inactive/error
- **RAG系统状态**: active/inactive
- **数据集状态**: active/archived
- **评估状态**: pending/running/completed/failed
- **同步状态**: pending/running/completed/failed

---

## 附录：指标框架支持

### RAGAS框架指标
| 指标名称 | 中文名 | 分类 | 需要LLM | 需要Embedding |
|----------|--------|------|---------|---------------|
| faithfulness | 忠实度 | generation | ✓ | |
| answer_relevance | 回答相关性 | generation | ✓ | ✓ |
| context_precision | 上下文精确度 | retrieval | | |
| context_recall | 上下文召回 | retrieval | | |
| answer_correctness | 回答正确性 | generation | ✓ | ✓ |

### EvalScope框架指标
| 指标名称 | 中文名 | 分类 |
|----------|--------|------|
| bleu | BLEU分数 | generation |
| rouge | ROUGE分数 | generation |
| bert_score | BERTScore | generation |

---

> 文档版本: 1.0.0
> 最后更新: 2026-04-03