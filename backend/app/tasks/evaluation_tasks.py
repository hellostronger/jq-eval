# 评估相关异步任务
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging

from app.core.celery_app import celery_app
from app.core.database import get_db_context
from app.models.evaluation import Evaluation, EvaluationStatus, EvalResult
from app.models.dataset import Dataset, QARecord
from app.models.model import ModelConfig, ModelType
from app.services.metrics import MetricEngine, get_metric_engine, METRIC_REGISTRY
from app.services.adapters import AdapterFactory

logger = logging.getLogger(__name__)


def run_async(coro):
    """在同步环境中运行异步函数"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, name="evaluation_task")
def evaluation_task(self, evaluation_id: int) -> Dict[str, Any]:
    """执行单个评估任务"""
    return run_async(_run_evaluation(self, evaluation_id))


async def _run_evaluation(task, evaluation_id: int) -> Dict[str, Any]:
    """异步执行评估"""
    async with get_db_context() as db:
        # 获取评估配置
        evaluation = await db.get(Evaluation, evaluation_id)
        if not evaluation:
            return {"error": f"评估任务 {evaluation_id} 不存在"}

        # 更新状态
        evaluation.status = EvaluationStatus.RUNNING
        evaluation.started_at = datetime.utcnow()
        await db.commit()

        try:
            # 获取数据集和QA记录
            dataset = await db.get(Dataset, evaluation.dataset_id)
            if not dataset:
                raise ValueError(f"数据集 {evaluation.dataset_id} 不存在")

            # 获取QA记录
            qa_records = await db.execute(
                """
                SELECT qr.*, ds.snapshot_version
                FROM qa_records qr
                JOIN dataset_snapshots ds ON qr.snapshot_id = ds.id
                WHERE ds.dataset_id = :dataset_id
                ORDER BY qr.created_at
                """,
                {"dataset_id": dataset.id}
            )
            qa_list = [dict(r) for r in qa_records.fetchall()]

            # 获取模型配置
            llm_config = await db.get(ModelConfig, evaluation.llm_model_id)
            embedding_config = await db.get(ModelConfig, evaluation.embedding_model_id) if evaluation.embedding_model_id else None

            # 初始化模型
            llm = await _init_model(llm_config)
            embedding_model = await _init_model(embedding_config) if embedding_config else None

            # 获取指标配置
            metric_configs = await db.execute(
                """
                SELECT * FROM evaluation_metric_configs
                WHERE evaluation_id = :eval_id AND enabled = true
                """,
                {"eval_id": evaluation_id}
            )
            metric_names = [r.metric_name for r in metric_configs.fetchall()]

            # 创建评估引擎
            engine = get_metric_engine(
                llm=llm,
                embedding_model=embedding_model,
                metric_names=metric_names
            )

            # 执行评估
            def progress_callback(progress, current, total):
                task.update_state(
                    state="PROGRESS",
                    meta={"progress": progress, "current": current, "total": total}
                )

            results = await engine.evaluate_batch(
                qa_records=qa_list,
                batch_size=evaluation.batch_size or 10,
                progress_callback=progress_callback
            )

            # 保存结果
            for i, result_dict in enumerate(results):
                qa_record = qa_list[i]
                eval_result = EvalResult(
                    evaluation_id=evaluation_id,
                    qa_record_id=qa_record["id"],
                    metric_scores=result_dict,
                    created_at=datetime.utcnow()
                )
                db.add(eval_result)

            # 计算汇总
            summary = MetricEngine.compute_summary(results)
            evaluation.summary = summary
            evaluation.status = EvaluationStatus.COMPLETED
            evaluation.completed_at = datetime.utcnow()
            await db.commit()

            return {
                "evaluation_id": evaluation_id,
                "status": "completed",
                "total_records": len(qa_list),
                "summary": summary
            }

        except Exception as e:
            logger.error(f"评估任务 {evaluation_id} 失败: {e}")
            evaluation.status = EvaluationStatus.FAILED
            evaluation.error_message = str(e)
            evaluation.completed_at = datetime.utcnow()
            await db.commit()
            return {"error": str(e)}


@celery_app.task(bind=True, name="batch_evaluation_task")
def batch_evaluation_task(self, evaluation_ids: List[int]) -> Dict[str, Any]:
    """批量执行评估任务"""
    results = []
    for eval_id in evaluation_ids:
        result = evaluation_task(eval_id)
        results.append(result)
    return {"total": len(evaluation_ids), "results": results}


async def _init_model(model_config: ModelConfig) -> Any:
    """初始化模型"""
    if model_config.model_type == ModelType.LLM:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_config.model_name,
            api_key=model_config.api_key,
            base_url=model_config.api_base,
            temperature=model_config.temperature or 0.7,
        )
    elif model_config.model_type == ModelType.EMBEDDING:
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(
            model=model_config.model_name,
            api_key=model_config.api_key,
            base_url=model_config.api_base,
        )
    return None