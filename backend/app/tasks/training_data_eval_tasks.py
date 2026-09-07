# 训练数据评估异步任务
import asyncio
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging
from sqlalchemy import select, text
from uuid import UUID

from app.core.celery_app import celery_app
from app.core.database import get_db_context
from app.models.training_data_eval import (
    TrainingDataEval,
    TrainingDataEvalResult,
    TrainingDataMetricConfig,
    TrainingDataEvalStatus
)
from app.models.dataset import Dataset, QARecord
from app.models.model import Model
from app.services.llm import create_llm_from_config, create_embeddings_from_config
from app.services.training_data.engine import (
    TrainingDataMetricEngine,
    get_training_data_engine,
    TRAINING_DATA_METRIC_REGISTRY
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


class _LLMTextAdapter:
    """将 LangChain LLM 适配为指标使用的异步文本接口

    指标内部统一 `await llm.generate(prompt)` 获取文本回复，
    底层通过 ainvoke 实现（可被 LLMCallLogger 再包装）。
    """

    def __init__(self, llm):
        self.llm = llm

    async def generate(self, prompt: str, **kwargs) -> str:
        response = await self.llm.ainvoke(prompt, **kwargs)
        if hasattr(response, "content"):
            return response.content
        return str(response)


@celery_app.task(bind=True, name="training_data_eval_task")
def training_data_eval_task(self, eval_id: str) -> Dict[str, Any]:
    """执行训练数据评估任务

    Args:
        eval_id: 评估任务ID (UUID字符串格式)
    """
    return run_async(_run_training_data_eval(self, UUID(eval_id)))


async def _run_training_data_eval(task, eval_id: UUID) -> Dict[str, Any]:
    """异步执行训练数据评估"""
    async with get_db_context() as db:
        # 获取评估配置
        evaluation = await db.get(TrainingDataEval, eval_id)
        if not evaluation:
            return {"error": f"评估任务 {eval_id} 不存在"}

        # 更新状态
        evaluation.status = TrainingDataEvalStatus.RUNNING
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
                SELECT id, question, answer, ground_truth, snapshot, qa_metadata FROM qa_records
                WHERE dataset_id = :dataset_id
                ORDER BY created_at
                """),
                {"dataset_id": dataset.id}
            )
            qa_list = [dict(r._mapping) for r in qa_records.fetchall()]

            if not qa_list:
                raise ValueError(f"数据集 {dataset.name} 中没有可评估的样本")

            evaluation.total_samples = len(qa_list)

            # 获取指标配置
            metric_configs_result = await db.execute(
                select(TrainingDataMetricConfig).where(
                    TrainingDataMetricConfig.eval_id == eval_id,
                    TrainingDataMetricConfig.enabled == True
                )
            )
            metric_configs = [
                {
                    "metric_name": c.metric_name,
                    "params": c.params or {},
                    "weight": c.weight,
                    "threshold": c.threshold
                }
                for c in metric_configs_result.scalars().all()
            ]

            # 如果没有配置，使用默认指标
            if not metric_configs:
                metric_configs = _get_default_metrics(evaluation.data_type)

            # 根据指标依赖加载模型：requires_llm / requires_embedding
            needs_llm = any(
                c["metric_name"] in TRAINING_DATA_METRIC_REGISTRY
                and TRAINING_DATA_METRIC_REGISTRY[c["metric_name"]].requires_llm
                for c in metric_configs
            )
            needs_embedding = any(
                c["metric_name"] in TRAINING_DATA_METRIC_REGISTRY
                and TRAINING_DATA_METRIC_REGISTRY[c["metric_name"]].requires_embedding
                for c in metric_configs
            )

            llm = None
            embedding_model = None
            if needs_llm:
                llm_model_id = (evaluation.config or {}).get("llm_model_id")
                if not llm_model_id:
                    raise ValueError("所选评估指标需要 LLM 模型，请在创建评估任务时指定评估用 LLM")
                llm_model = await db.get(Model, UUID(str(llm_model_id)))
                if not llm_model or llm_model.model_type != "llm":
                    raise ValueError(f"评估用 LLM 模型 {llm_model_id} 不存在或类型错误")
                llm = await create_llm_from_config(llm_model)

                # 按模型的 save_logs 开关挂接调用日志（失败不影响评估）
                try:
                    from app.services.llm import create_log_recorder, LLMCallLogger
                    recorder = await create_log_recorder(db, llm_model.id)
                    if recorder.is_enabled():
                        llm = LLMCallLogger(llm, recorder, request_type="chat")
                except Exception as e:
                    logger.warning(f"挂接模型调用日志失败: {e}")

                # 指标统一通过 await llm.generate(prompt) 调用；
                # 原生 ChatOpenAI.generate 是同步方法且参数不同，这里补一个异步文本适配
                if not asyncio.iscoroutinefunction(getattr(llm, "generate", None)):
                    llm = _LLMTextAdapter(llm)

            if needs_embedding:
                embedding_model_id = (evaluation.config or {}).get("embedding_model_id")
                if not embedding_model_id:
                    raise ValueError("所选评估指标需要 Embedding 模型，请在创建评估任务时指定评估用 Embedding")
                emb_model = await db.get(Model, UUID(str(embedding_model_id)))
                if not emb_model or emb_model.model_type != "embedding":
                    raise ValueError(f"评估用 Embedding 模型 {embedding_model_id} 不存在或类型错误")
                embedding_model = await create_embeddings_from_config(emb_model)

            # 创建评估引擎
            engine = get_training_data_engine(
                data_type=evaluation.data_type,
                llm=llm,
                embedding_model=embedding_model,
                metric_configs=metric_configs
            )

            # 准备评估数据
            # contexts 来自 qa_records.snapshot['contexts']；
            # qa_metadata 中可携带各数据类型的专属字段，直接透传给指标 kwargs：
            # - reranker: positive_doc / negative_doc / label / doc_content / is_hard_negative
            # - dpo / reward_model: chosen / rejected / preference_score / confidence
            # - vlm / vla: image_description / action
            eval_data = []
            for qa in qa_list:
                snapshot = qa.get("snapshot") or {}
                if not isinstance(snapshot, dict):
                    snapshot = {}
                eval_item = {
                    "question": qa.get("question") or "",
                    "answer": qa.get("answer") or "",
                    "ground_truth": qa.get("ground_truth"),
                    "contexts": snapshot.get("contexts"),
                }
                qa_metadata = qa.get("qa_metadata") or {}
                if isinstance(qa_metadata, dict):
                    for key, value in qa_metadata.items():
                        if key not in eval_item and value is not None:
                            eval_item[key] = value
                eval_data.append(eval_item)

            # 执行评估
            def progress_callback(progress, current, total):
                task.update_state(
                    state="PROGRESS",
                    meta={"progress": progress, "current": current, "total": total}
                )

            results = await engine.evaluate_batch(
                records=eval_data,
                batch_size=(evaluation.config or {}).get("batch_size", 10),
                progress_callback=progress_callback
            )

            # 保存结果
            passed_count = 0
            failed_count = 0
            for i, result_dict in enumerate(results):
                qa = qa_list[i]

                # 计算整体得分
                valid_scores = [v.score for v in result_dict.values()
                              if v.error is None and v.score is not None]
                overall_score = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0

                # 判断是否通过
                status = "passed" if overall_score >= 0.7 else "failed"
                if status == "passed":
                    passed_count += 1
                else:
                    failed_count += 1

                # 收集质量标签和问题
                quality_tags = []
                issues = []
                suggestions = []
                for metric_name, metric_result in result_dict.items():
                    if not metric_result.passed:
                        issues.append(f"{metric_name}: 未通过")
                    if metric_result.suggestions:
                        suggestions.extend(metric_result.suggestions)
                    if metric_result.passed and metric_result.score >= 0.9:
                        quality_tags.append(f"{metric_name}: 优秀")

                # 保存评估结果
                scores_dict = {}
                details_dict = {}
                for metric_name, metric_result in result_dict.items():
                    scores_dict[metric_name] = {
                        "score": metric_result.score,
                        "passed": metric_result.passed
                    }
                    if metric_result.details:
                        details_dict[metric_name] = metric_result.details

                eval_result = TrainingDataEvalResult(
                    eval_id=eval_id,
                    qa_record_id=qa["id"],
                    scores=scores_dict,
                    details=details_dict,
                    quality_tags=list(set(quality_tags)),
                    issues=list(set(issues)),
                    suggestions=list(set(suggestions)),
                    status=status,
                    overall_score=overall_score
                )
                db.add(eval_result)

            # 计算汇总
            summary = engine.compute_summary(results)
            suggestions = engine.generate_suggestions(results)

            evaluation.summary = summary
            evaluation.passed_samples = passed_count
            evaluation.failed_samples = failed_count
            evaluation.pass_rate = passed_count / evaluation.total_samples if evaluation.total_samples > 0 else 0.0
            evaluation.quality_distribution = summary.get("quality_distribution", {})
            evaluation.status = TrainingDataEvalStatus.COMPLETED
            evaluation.completed_at = datetime.utcnow()
            await db.commit()

            return {
                "eval_id": str(eval_id),
                "status": "completed",
                "total_samples": len(qa_list),
                "passed_samples": passed_count,
                "failed_samples": failed_count,
                "pass_rate": evaluation.pass_rate,
                "summary": summary,
                "suggestions": suggestions
            }

        except Exception as e:
            logger.error(f"训练数据评估任务 {eval_id} 失败: {e}")
            await db.rollback()

            evaluation = await db.get(TrainingDataEval, eval_id)
            if evaluation:
                evaluation.status = TrainingDataEvalStatus.FAILED
                evaluation.error = str(e)
                evaluation.completed_at = datetime.utcnow()
                await db.commit()

            return {"error": str(e)}


def _get_default_metrics(data_type: str) -> List[Dict[str, Any]]:
    """获取默认指标配置（指标名必须存在于 TRAINING_DATA_METRIC_REGISTRY）"""
    default_metrics = {
        "llm": [
            {"metric_name": "llm_response_quality"},
            {"metric_name": "llm_coherence"},
            {"metric_name": "llm_response_length"},
        ],
        "embedding": [
            {"metric_name": "embedding_quality"},
            {"metric_name": "embedding_completeness"},
            {"metric_name": "embedding_text_length"},
        ],
        "reranker": [
            {"metric_name": "reranker_pair_quality"},
            {"metric_name": "reranker_label_consistency"},
        ],
        "reward_model": [
            {"metric_name": "reward_model_pair_quality"},
            {"metric_name": "reward_model_label_confidence"},
        ],
        "dpo": [
            {"metric_name": "dpo_pair_quality"},
            {"metric_name": "dpo_preference_strength"},
        ],
        "vlm": [
            {"metric_name": "vlm_image_text_alignment"},
            {"metric_name": "vlm_question_relevance"},
        ],
        "vla": [
            {"metric_name": "vla_action_reasoning"},
            {"metric_name": "vla_instruction_clarity"},
        ],
    }
    # 过滤注册表中不存在的指标，避免引擎静默丢弃全部指标
    defaults = default_metrics.get(data_type, [])
    return [m for m in defaults if m["metric_name"] in TRAINING_DATA_METRIC_REGISTRY]


@celery_app.task(bind=True, name="batch_training_data_eval_task")
def batch_training_data_eval_task(self, eval_ids: List[str]) -> Dict[str, Any]:
    """批量执行训练数据评估任务

    Args:
        eval_ids: 评估任务ID列表 (UUID字符串格式)
    """
    results = []
    for eval_id in eval_ids:
        result = training_data_eval_task(eval_id)
        results.append(result)
    return {"total": len(eval_ids), "results": results}
