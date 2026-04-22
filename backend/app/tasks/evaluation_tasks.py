# 评估相关异步任务
import asyncio
import os
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging
from sqlalchemy import text, select
from uuid import UUID

from app.core.celery_app import celery_app
from app.core.database import get_db_context
from app.models.evaluation import Evaluation, EvaluationStatus, EvalResult
from app.models.dataset import Dataset, QARecord
from app.models.model import Model
from app.models.invocation import InvocationBatch, InvocationResult
from app.models.rag_system import RAGSystem
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
def evaluation_task(self, evaluation_id: str) -> Dict[str, Any]:
    """执行单个评估任务

    Args:
        evaluation_id: 评估任务ID (UUID字符串格式)
    """
    return run_async(_run_evaluation(self, UUID(evaluation_id)))


async def _run_evaluation(task, evaluation_id: UUID) -> Dict[str, Any]:
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
                text("""
                SELECT id, question, answer, ground_truth, target_chunk_ids FROM qa_records
                WHERE dataset_id = :dataset_id
                ORDER BY created_at
                """),
                {"dataset_id": dataset.id}
            )
            qa_list = [dict(r._mapping) for r in qa_records.fetchall()]

            # 获取调用结果（如果指定了 invocation_batch_id）
            invocation_results_map = {}
            if evaluation.invocation_batch_id:
                invocation_results = await db.execute(
                    select(InvocationResult)
                    .where(InvocationResult.batch_id == evaluation.invocation_batch_id)
                )
                for ir in invocation_results.scalars().all():
                    invocation_results_map[str(ir.qa_record_id)] = ir

            # 获取模型配置
            logger.info(f"评估任务模型配置: llm_model_id={evaluation.llm_model_id}, embedding_model_id={evaluation.embedding_model_id}")

            llm_config = await db.get(Model, evaluation.llm_model_id) if evaluation.llm_model_id else None
            embedding_config = await db.get(Model, evaluation.embedding_model_id) if evaluation.embedding_model_id else None

            logger.info(f"获取到的模型配置: llm_config={llm_config}, embedding_config={embedding_config}")

            # 设置环境变量供ragas内部创建LLM/Embedding使用
            if llm_config:
                if llm_config.api_key_encrypted:
                    os.environ["OPENAI_API_KEY"] = llm_config.api_key_encrypted
                if llm_config.endpoint:
                    os.environ["OPENAI_API_BASE"] = llm_config.endpoint
                logger.info(f"设置环境变量: OPENAI_API_KEY={'已设置' if llm_config.api_key_encrypted else '未设置'}, OPENAI_API_BASE={llm_config.endpoint}")

            # 初始化模型
            llm = await _init_model(llm_config) if llm_config else None
            embedding_model = await _init_model(embedding_config) if embedding_config else None

            logger.info(f"初始化后的模型: llm={llm}, embedding_model={embedding_model}")

            # 检查是否有必要的模型配置
            if not llm:
                raise ValueError("评估任务需要配置 LLM 模型")

            # 直接使用 evaluation.metrics 数组中的指标名称
            metric_names = evaluation.metrics or []
            logger.info(f"评估指标列表: metric_names={metric_names}")

            # 创建评估引擎
            engine = get_metric_engine(
                llm=llm,
                embedding_model=embedding_model,
                metric_names=metric_names
            )
            logger.info(f"评估引擎初始化后的指标: engine.metrics={list(engine.metrics.keys())}")

            # 准备评估数据：根据 reuse_invocation 决定数据来源
            eval_data = []
            for qa in qa_list:
                qa_id = str(qa["id"])
                # 如果有调用结果且 reuse_invocation=True，使用调用结果
                if evaluation.reuse_invocation and qa_id in invocation_results_map:
                    ir = invocation_results_map[qa_id]
                    eval_item = {
                        "id": qa["id"],
                        "question": qa["question"],
                        "answer": ir.answer or qa.get("answer"),
                        "contexts": ir.contexts or qa.get("contexts"),
                        "ground_truth": qa.get("ground_truth"),
                        "retrieval_ids": ir.retrieval_ids or [],
                        "target_chunk_ids": qa.get("target_chunk_ids") or [],
                        "invocation_result_id": ir.id,
                    }
                else:
                    # 使用 QARecord 的原始数据
                    eval_item = {
                        "id": qa["id"],
                        "question": qa["question"],
                        "answer": qa.get("answer"),
                        "contexts": qa.get("contexts"),
                        "ground_truth": qa.get("ground_truth"),
                        "retrieval_ids": [],
                        "target_chunk_ids": qa.get("target_chunk_ids") or [],
                        "invocation_result_id": None,
                    }
                eval_data.append(eval_item)

            # 执行评估
            def progress_callback(progress, current, total):
                task.update_state(
                    state="PROGRESS",
                    meta={"progress": progress, "current": current, "total": total}
                )

            results = await engine.evaluate_batch(
                qa_records=eval_data,
                batch_size=evaluation.batch_size or 10,
                progress_callback=progress_callback
            )

            # 保存结果 - 将 MetricResult 转换成字典
            for i, result_dict in enumerate(results):
                eval_item = eval_data[i]
                # 转换 MetricResult 对象为可序列化的字典
                scores_dict = {}
                for metric_name, metric_result in result_dict.items():
                    scores_dict[metric_name] = {
                        "score": metric_result.score,
                        "details": metric_result.details,
                        "error": metric_result.error
                    }
                eval_result = EvalResult(
                    eval_id=evaluation_id,
                    qa_record_id=eval_item["id"],
                    invocation_result_id=eval_item.get("invocation_result_id"),
                    scores=scores_dict,
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
            # 回滚失败的事务
            await db.rollback()
            # 重新获取 evaluation 对象并更新状态
            evaluation = await db.get(Evaluation, evaluation_id)
            if evaluation:
                evaluation.status = EvaluationStatus.FAILED
                evaluation.error = str(e)
                evaluation.completed_at = datetime.utcnow()
                await db.commit()
            return {"error": str(e)}


@celery_app.task(bind=True, name="batch_evaluation_task")
def batch_evaluation_task(self, evaluation_ids: List[str]) -> Dict[str, Any]:
    """批量执行评估任务

    Args:
        evaluation_ids: 评估任务ID列表 (UUID字符串格式)
    """
    results = []
    for eval_id in evaluation_ids:
        result = evaluation_task(eval_id)
        results.append(result)
    return {"total": len(evaluation_ids), "results": results}


async def _init_model(model_config: Model) -> Any:
    """初始化模型"""
    params = model_config.params or {}
    model_type = model_config.model_type.lower() if model_config.model_type else ""

    logger.info(f"初始化模型: id={model_config.id}, name={model_config.name}, type={model_type}")
    logger.info(f"模型配置详情: endpoint={model_config.endpoint}, model_name={model_config.model_name}, api_key={'已设置' if model_config.api_key_encrypted else '未设置'}")

    if model_type == "llm":
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=model_config.model_name,
            api_key=model_config.api_key_encrypted,
            base_url=model_config.endpoint,
            temperature=params.get("temperature", 0.7),
        )
        # 验证 LLM 是否正确初始化
        logger.info(f"ChatOpenAI 初始化完成: model={llm.model_name}, api_base={llm.openai_api_base}, has_api_key={bool(llm.openai_api_key)}")
        return llm
    elif model_type == "embedding":
        from langchain_openai import OpenAIEmbeddings
        emb = OpenAIEmbeddings(
            model=model_config.model_name,
            api_key=model_config.api_key_encrypted,
            base_url=model_config.endpoint,
        )
        logger.info(f"OpenAIEmbeddings 初始化完成: model={emb.model}, has_api_key={bool(emb.openai_api_key)}")
        return emb
    else:
        logger.warning(f"未知的模型类型: {model_config.model_type}, 模型ID: {model_config.id}")
        return None