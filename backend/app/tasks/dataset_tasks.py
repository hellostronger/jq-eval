# 数据集生成异步任务
import asyncio
from typing import Dict, List, Any
from datetime import datetime
from uuid import UUID
import logging

from app.core.celery_app import celery_app
from app.core.database import get_db_context
from app.models.dataset import Dataset, QARecord
from app.models.model import Model
from app.services.dataset import (
    DatasetGenerator,
    AdapterFactory,
)
from app.services.llm import (
    create_llm_from_config,
    create_embeddings_from_config,
)

logger = logging.getLogger(__name__)


def run_async(coro):
    """在同步环境中运行异步函数"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, name="generate_dataset_task")
def generate_dataset_task(self, dataset_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """生成测试数据集的异步任务

    Args:
        dataset_id: 数据集 UUID
        config: 生成配置
            - sources: 文档源配置列表
            - test_size: 生成数量
            - distributions: 问题类型分布
            - llm_model_id: LLM 模型 ID
            - embedding_model_id: Embedding 模型 ID

    Returns:
        任务结果
    """
    return run_async(_run_generate_task(self, UUID(dataset_id), config))


async def _run_generate_task(task, dataset_id: UUID, config: Dict[str, Any]) -> Dict[str, Any]:
    """异步执行生成任务"""
    async with get_db_context() as db:
        # 1. 获取数据集
        dataset = await db.get(Dataset, dataset_id)
        if not dataset:
            return {"error": f"数据集 {dataset_id} 不存在"}

        # 2. 更新状态
        dataset.status = "generating"
        await db.commit()

        try:
            # 3. 获取模型配置
            llm_model_id = UUID(config.get("llm_model_id"))
            embedding_model_id = UUID(config.get("embedding_model_id"))

            llm_model = await db.get(Model, llm_model_id)
            embedding_model = await db.get(Model, embedding_model_id)

            if not llm_model or llm_model.model_type != "llm":
                raise ValueError(f"LLM 模型 {llm_model_id} 不存在或类型错误")

            if not embedding_model or embedding_model.model_type != "embedding":
                raise ValueError(f"Embedding 模型 {embedding_model_id} 不存在或类型错误")

            # 4. 创建 LLM/Embeddings 客户端
            llm = await create_llm_from_config(llm_model)
            embeddings = await create_embeddings_from_config(embedding_model)

            # 5. 创建适配器
            sources = config.get("sources", [])
            adapters = []

            for source in sources:
                source_type = source.get("source_type")
                adapter = AdapterFactory.create_adapter(source_type, source, db)
                adapters.append(adapter)

            # 创建多源适配器
            if len(adapters) == 1:
                adapter = adapters[0]
            else:
                from app.services.dataset.adapters.base import MultiSourceAdapter
                adapter = MultiSourceAdapter(adapters)

            # 6. 初始化生成器并生成数据
            generator = DatasetGenerator(llm, embeddings)

            # 更新进度
            task.update_state(
                state="PROGRESS",
                meta={"progress": 30, "stage": "loading_documents"}
            )

            qa_records = await generator.generate(
                adapter=adapter,
                test_size=config.get("test_size", 10),
                distributions=config.get("distributions")
            )

            task.update_state(
                state="PROGRESS",
                meta={"progress": 60, "stage": "saving_records", "total": len(qa_records)}
            )

            # 7. 保存到数据库
            for i, qa_data in enumerate(qa_records):
                qa_record = QARecord(
                    dataset_id=dataset_id,
                    question=qa_data["question"],
                    ground_truth=qa_data["ground_truth"],
                    snapshot={
                        "contexts": qa_data.get("contexts", []),
                        "evolution_type": qa_data.get("evolution_type", "unknown"),
                        "generated_at": datetime.utcnow().isoformat(),
                    },
                    question_type=qa_data.get("evolution_type", "simple"),
                    qa_metadata=qa_data.get("metadata", {}),
                )
                db.add(qa_record)

                # 每 10 条更新进度
                if (i + 1) % 10 == 0:
                    task.update_state(
                        state="PROGRESS",
                        meta={
                            "progress": 60 + int(30 * (i + 1) / len(qa_records)),
                            "stage": "saving_records",
                            "current": i + 1,
                            "total": len(qa_records)
                        }
                    )

            # 8. 更新数据集统计
            dataset.record_count += len(qa_records)
            dataset.has_ground_truth = True
            dataset.has_contexts = True
            dataset.status = "ready"

            await db.commit()

            return {
                "dataset_id": str(dataset_id),
                "status": "completed",
                "generated_count": len(qa_records),
                "sources": [s.get("source_type") for s in sources]
            }

        except Exception as e:
            logger.error(f"生成任务失败: {e}")
            dataset.status = "failed"
            await db.commit()

            return {"error": str(e), "dataset_id": str(dataset_id)}


@celery_app.task(bind=True, name="import_dataset_task")
def import_dataset_task(self, dataset_id: str, file_path: str, file_type: str) -> Dict[str, Any]:
    """导入数据集文件的异步任务

    Args:
        dataset_id: 数据集 UUID
        file_path: MinIO 文件路径
        file_type: 文件类型 (json/jsonl/csv)

    Returns:
        任务结果
    """
    return run_async(_run_import_task(self, UUID(dataset_id), file_path, file_type))


async def _run_import_task(
    task,
    dataset_id: UUID,
    file_path: str,
    file_type: str
) -> Dict[str, Any]:
    """异步执行导入任务"""
    from app.services.storage.minio_service import get_minio_service

    async with get_db_context() as db:
        dataset = await db.get(Dataset, dataset_id)
        if not dataset:
            return {"error": f"数据集 {dataset_id} 不存在"}

        dataset.status = "importing"
        await db.commit()

        try:
            # 下载文件
            minio_service = get_minio_service()
            download_result = await minio_service.download_file(
                bucket="datasets",
                object_name=file_path
            )

            if not download_result.get("success"):
                raise ValueError(f"下载文件失败: {download_result.get('error')}")

            file_data = download_result["data"]
            records = []

            # 解析文件
            if file_type == "json":
                import json
                data = json.loads(file_data.decode("utf-8"))
                if isinstance(data, list):
                    records = data
                elif isinstance(data, dict) and "test_cases" in data:
                    records = data["test_cases"]

            elif file_type == "jsonl":
                import json
                lines = file_data.decode("utf-8").strip().split("\n")
                records = [json.loads(line) for line in lines if line]

            elif file_type == "csv":
                import csv
                import io
                reader = csv.DictReader(io.StringIO(file_data.decode("utf-8")))
                records = list(reader)

            else:
                raise ValueError(f"不支持的文件类型: {file_type}")

            # 保存到数据库
            task.update_state(
                state="PROGRESS",
                meta={"progress": 50, "stage": "saving_records", "total": len(records)}
            )

            for i, record in enumerate(records):
                qa_record = QARecord(
                    dataset_id=dataset_id,
                    question=record.get("question", ""),
                    answer=record.get("answer"),
                    ground_truth=record.get("ground_truth"),
                    question_type=record.get("question_type", "simple"),
                    difficulty=record.get("difficulty"),
                    qa_metadata=record.get("metadata", {}),
                )

                # 处理 contexts
                contexts = record.get("contexts")
                if contexts:
                    qa_record.snapshot = {"contexts": contexts if isinstance(contexts, list) else [contexts]}

                db.add(qa_record)

                if (i + 1) % 10 == 0:
                    task.update_state(
                        state="PROGRESS",
                        meta={
                            "progress": 50 + int(40 * (i + 1) / len(records)),
                            "current": i + 1,
                            "total": len(records)
                        }
                    )

            # 更新统计
            dataset.record_count += len(records)
            dataset.has_ground_truth = any(r.get("ground_truth") for r in records)
            dataset.has_contexts = any(r.get("contexts") for r in records)
            dataset.status = "ready"

            await db.commit()

            return {
                "dataset_id": str(dataset_id),
                "status": "completed",
                "imported_count": len(records),
                "file_type": file_type
            }

        except Exception as e:
            logger.error(f"导入任务失败: {e}")
            dataset.status = "failed"
            await db.commit()

            return {"error": str(e), "dataset_id": str(dataset_id)}