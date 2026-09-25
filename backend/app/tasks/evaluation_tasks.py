# 评估相关异步任务
import os
from typing import Dict, List, Any
from datetime import datetime
import logging
from sqlalchemy import text, select
from uuid import UUID

from app.core.celery_app import celery_app
from app.core.exceptions import TaskCancelled
from app.tasks._common import run_async, make_progress_callback, mark_task_failed, format_error
from app.core.database import get_db_context
from app.models.evaluation import Evaluation, EvaluationStatus, EvalResult
from app.models.dataset import Dataset, QARecord
from app.models.model import Model
from app.models.invocation import InvocationResult
from app.services.metrics import MetricEngine, get_metric_engine, METRIC_REGISTRY

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="evaluation_task",
                 soft_time_limit=110 * 60, time_limit=115 * 60)
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

        # acks_late 重投幂等：若结果 commit 成功但 worker 在 ack 前被杀，消息会重投递。
        # 无此保护将全量重打 LLM（浪费 token）并二次插入结果（数据翻倍）
        if evaluation.status == EvaluationStatus.COMPLETED:
            logger.warning(f"评估 {evaluation_id} 已完成但收到重复投递，跳过（acks_late 重投保护）")
            return {"evaluation_id": evaluation_id, "status": "already_completed",
                    "summary": evaluation.summary}

        # 更新状态
        evaluation.status = EvaluationStatus.RUNNING
        evaluation.started_at = datetime.utcnow()
        await db.commit()

        try:
            # 获取数据集和QA记录
            dataset = await db.get(Dataset, evaluation.dataset_id)
            if not dataset:
                raise ValueError(f"数据集 {evaluation.dataset_id} 不存在")

            # 获取QA记录。用 ORM 查询而非 text() 裸 SQL：text() 不做类型转换，
            # PostgreSQL 能隐式接受 UUID，SQLite 会抛
            # "Error binding parameter 0 - probably unsupported type"。
            qa_result = await db.execute(
                select(
                    QARecord.id,
                    QARecord.question,
                    QARecord.answer,
                    QARecord.ground_truth,
                    QARecord.target_chunk_ids,
                    QARecord.snapshot,
                )
                .where(QARecord.dataset_id == dataset.id)
                .order_by(QARecord.created_at)
            )
            qa_list = [dict(r._mapping) for r in qa_result.all()]

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

            # 按模型的 save_logs 开关挂接调用日志（失败不影响评估）
            if llm is not None and llm_config is not None:
                try:
                    from app.services.llm import create_log_recorder, LLMCallLogger
                    recorder = await create_log_recorder(db, llm_config.id)
                    if recorder.is_enabled():
                        llm = LLMCallLogger(llm, recorder, request_type="chat")
                except Exception as e:
                    logger.warning(f"挂接模型调用日志失败: {e}")

            logger.info(f"初始化后的模型: llm={llm}, embedding_model={embedding_model}")

            # 直接使用 evaluation.metrics 数组中的指标名称
            metric_names = evaluation.metrics or []
            selected_metrics = [(name, METRIC_REGISTRY[name]) for name in metric_names if name in METRIC_REGISTRY]
            need_llm = any(cls.requires_llm for _, cls in selected_metrics)
            need_embedding = any(cls.requires_embedding for _, cls in selected_metrics)

            if not selected_metrics:
                raise ValueError(f"没有可用的评估指标: {metric_names}，可用指标: {sorted(METRIC_REGISTRY.keys())}")

            if need_llm and not llm:
                raise ValueError("评估任务需要配置 LLM 模型（所选指标包含生成阶段指标）")
            if need_embedding and not embedding_model:
                raise ValueError("评估任务需要配置 Embedding 模型（所选指标依赖向量相似度）")

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
                    # 不能用 `ir.answer or qa.get("answer")` 兜底：调用失败时
                    # ir.answer 为空，回落到 QARecord 的静态答案，等于拿
                    # "标准答案"当成 RAG 的输出来打分——失败会被记成满分。
                    # 复用调用结果时，答案只能来自调用结果本身。
                    eval_item = {
                        "id": qa["id"],
                        "question": qa["question"],
                        "answer": ir.answer or "",
                        "contexts": ir.contexts or [],
                        "ground_truth": qa.get("ground_truth"),
                        "retrieval_ids": ir.retrieval_ids or [],
                        "target_chunk_ids": qa.get("target_chunk_ids") or [],
                        "invocation_result_id": ir.id,
                        # RAG 调用本身的失败原因。丢掉它的话，报告里只会看到
                        # "答案为空"这类下游报错，用户根本看不出是 RAG 挂了
                        # 还是评估算错了，排查方向完全被带偏。
                        "invocation_error": ir.error,
                    }
                else:
                    # 使用 QARecord 的原始数据（contexts 存于 snapshot 字段）
                    snapshot = qa.get("snapshot") or {}
                    eval_item = {
                        "id": qa["id"],
                        "question": qa["question"],
                        "answer": qa.get("answer"),
                        "contexts": snapshot.get("contexts"),
                        "ground_truth": qa.get("ground_truth"),
                        "retrieval_ids": [],
                        "target_chunk_ids": qa.get("target_chunk_ids") or [],
                        "invocation_result_id": None,
                        "invocation_error": None,
                    }
                eval_data.append(eval_item)

            # 执行评估
            progress_callback = make_progress_callback(task)

            async def _check_cancel():
                # 协作式取消：批次边界重读取消标志（独立短查询，不依赖当前事务对象）
                flag = await db.execute(
                    select(Evaluation.cancel_requested).where(Evaluation.id == evaluation_id)
                )
                if flag.scalar():
                    raise TaskCancelled()

            results = await engine.evaluate_batch(
                qa_records=eval_data,
                batch_size=evaluation.batch_size or 10,
                progress_callback=progress_callback,
                check_cancel=_check_cancel,
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
                    # 把上游调用失败原因留在明细里，评估详情页可据此归因
                    details=(
                        {"invocation_error": eval_item["invocation_error"]}
                        if eval_item.get("invocation_error")
                        else None
                    ),
                )
                db.add(eval_result)

            # 计算汇总
            summary = MetricEngine.compute_summary(results)
            # RAG 调用失败的样本单独记账：不记的话，"低分"和"压根没调用成功"
            # 在报告里长得一样，指标算不出来时还会被误读成模型质量问题
            invocation_errors = [
                e["invocation_error"] for e in eval_data if e.get("invocation_error")
            ]
            if invocation_errors:
                summary["invocation_failed_count"] = len(invocation_errors)
                seen, uniq = set(), []
                for e in invocation_errors:
                    if e not in seen:
                        seen.add(e)
                        uniq.append(e)
                summary["invocation_errors"] = uniq[:5]
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

        except TaskCancelled:
            # 用户协作式取消：丢弃未落库的部分批次结果（结果只在全部完成后保存），
            # 状态标记 cancelled 并清除取消标志，供重试
            logger.info(f"评估任务 {evaluation_id} 已被用户取消")
            await db.rollback()
            evaluation = await db.get(Evaluation, evaluation_id)
            if evaluation:
                evaluation.status = EvaluationStatus.CANCELLED
                evaluation.error = "任务已被用户取消"
                evaluation.cancel_requested = False
                evaluation.completed_at = datetime.utcnow()
                await db.commit()
            return {"evaluation_id": evaluation_id, "status": "cancelled"}

        except Exception as e:
            await mark_task_failed(db, Evaluation, evaluation_id, format_error(e), logger)
            return {"error": format_error(e)}


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
            # 出站超时与重试（与 create_llm_from_config 保持一致），防止挂死拖垮 worker
            request_timeout=params.get("timeout", 300),
            max_retries=params.get("max_retries", 2),
            model_kwargs=params.get("extra_params") or {},
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
            request_timeout=params.get("timeout", 120),
            max_retries=params.get("max_retries", 2),
        )
        logger.info(f"OpenAIEmbeddings 初始化完成: model={emb.model}, has_api_key={bool(emb.openai_api_key)}")
        return emb
    else:
        logger.warning(f"未知的模型类型: {model_config.model_type}, 模型ID: {model_config.id}")
        return None