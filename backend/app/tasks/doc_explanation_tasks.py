# 文档解释评估Celery任务
import asyncio
from typing import Dict, List, Any
from datetime import datetime
import logging
import statistics
from uuid import UUID

from app.core.celery_app import celery_app
from app.core.database import get_db_context
from app.models import DocExplanationEvaluation, DocExplanationEvalResult, DocExplanationEvalStatus, DocExplanation, Document, Model
from sqlalchemy import select

logger = logging.getLogger(__name__)


def run_async(coro):
    """在同步环境中运行异步函数"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, name="doc_explanation_eval_task")
def doc_explanation_eval_task(self, eval_id: str) -> Dict[str, Any]:
    """执行文档解释评估任务"""
    return run_async(_run_doc_explanation_eval(self, UUID(eval_id)))


async def _run_doc_explanation_eval(task, eval_id: UUID) -> Dict[str, Any]:
    """异步执行文档解释评估"""
    async with get_db_context() as db:
        evaluation = await db.get(DocExplanationEvaluation, eval_id)
        if not evaluation:
            return {"error": f"评估任务 {eval_id} 不存在"}

        evaluation.status = DocExplanationEvalStatus.RUNNING.value
        evaluation.started_at = datetime.utcnow()
        await db.commit()

        try:
            # 获取LLM模型配置
            llm_model = await db.get(Model, evaluation.llm_model_id)
            if not llm_model:
                raise ValueError(f"模型 {evaluation.llm_model_id} 不存在")

            # 获取待评估的文档解释
            if evaluation.doc_ids:
                doc_ids = evaluation.doc_ids
            else:
                # 获取所有有解释的文档
                explanations = await db.execute(select(DocExplanation))
                doc_ids = [exp.doc_id for exp in explanations.scalars().all()]

            # 获取文档和解释数据
            eval_data = []
            for doc_id in doc_ids:
                doc = await db.get(Document, doc_id)
                if not doc:
                    continue

                exp_result = await db.execute(
                    select(DocExplanation).where(DocExplanation.doc_id == doc_id)
                )
                explanation = exp_result.scalar_one_or_none()
                if not explanation:
                    continue

                eval_data.append({
                    "doc_id": doc_id,
                    "doc_title": doc.title,
                    "doc_content": doc.content,
                    "explanation_id": explanation.id,
                    "explanation": explanation.explanation,
                })

            if not eval_data:
                raise ValueError("没有可评估的文档解释")

            # 初始化LLM
            llm = await _init_llm(llm_model)

            # 执行评估
            metrics = evaluation.metrics or ["completeness", "accuracy", "info_missing", "explanation_error"]
            results = []

            total = len(eval_data)
            for idx, item in enumerate(eval_data):
                # 更新进度
                progress = int((idx / total) * 100)
                evaluation.progress = progress
                await db.commit()

                # 对每个解释进行评估
                scores = await _evaluate_explanation(
                    llm=llm,
                    doc_content=item["doc_content"],
                    doc_title=item["doc_title"],
                    explanation=item["explanation"],
                    metrics=metrics
                )

                result = DocExplanationEvalResult(
                    eval_id=eval_id,
                    doc_id=item["doc_id"],
                    explanation_id=item["explanation_id"],
                    scores=scores,
                    details={"doc_title": item["doc_title"]},
                )
                db.add(result)
                results.append(scores)

            # 计算汇总
            summary = _compute_summary(results, metrics)
            evaluation.summary = summary
            evaluation.status = DocExplanationEvalStatus.COMPLETED.value
            evaluation.completed_at = datetime.utcnow()
            evaluation.progress = 100
            await db.commit()

            return {
                "eval_id": str(eval_id),
                "status": "completed",
                "total_evaluated": len(results),
                "summary": summary
            }

        except Exception as e:
            logger.error(f"文档解释评估任务 {eval_id} 失败: {e}")
            await db.rollback()
            evaluation = await db.get(DocExplanationEvaluation, eval_id)
            if evaluation:
                evaluation.status = DocExplanationEvalStatus.FAILED.value
                evaluation.error = str(e)
                evaluation.completed_at = datetime.utcnow()
                await db.commit()
            return {"error": str(e)}


async def _init_llm(model_config: Model) -> Any:
    """初始化LLM模型"""
    from langchain_openai import ChatOpenAI
    params = model_config.params or {}

    llm = ChatOpenAI(
        model=model_config.model_name,
        api_key=model_config.api_key_encrypted,
        base_url=model_config.endpoint,
        temperature=params.get("temperature", 0.0),
    )
    return llm


async def _evaluate_explanation(
    llm: Any,
    doc_content: str,
    doc_title: str,
    explanation: str,
    metrics: List[str]
) -> Dict[str, Any]:
    """使用LLM评估文档解释"""
    prompt = f"""请对以下文档解释进行评估。

文档标题: {doc_title or '未知'}

文档内容:
{doc_content[:2000] if doc_content else '无内容'}

解释内容:
{explanation}

请从以下几个维度进行评估，每个维度给出0-10分的评分（0分最差，10分最好）:

1. completeness (完整性): 解释是否完整地覆盖了文档的主要内容
2. accuracy (准确性): 解释是否准确反映了文档的实际内容
3. info_missing (信息遗漏): 是否有重要信息被遗漏（分数越高表示遗漏越少）
4. explanation_error (解释错误): 是否存在解释错误或曲解（分数越高表示错误越少）

请以JSON格式输出评分结果，格式如下:
{{"completeness": X, "accuracy": X, "info_missing": X, "explanation_error": X, "analysis": "简要分析说明"}}
"""

    try:
        response = await llm.ainvoke(prompt)
        content = response.content

        # 解析JSON结果
        import json
        import re

        # 提取JSON部分
        json_match = re.search(r'\{[^{}]+\}', content)
        if json_match:
            scores = json.loads(json_match.group())
        else:
            scores = {"completeness": 5, "accuracy": 5, "info_missing": 5, "explanation_error": 5, "analysis": content}

        # 确保所有指标都有值
        for metric in metrics:
            if metric not in scores:
                scores[metric] = 5

        return scores

    except Exception as e:
        logger.error(f"LLM评估失败: {e}")
        return {metric: 5 for metric in metrics}


def _compute_summary(results: List[Dict], metrics: List[str]) -> Dict[str, Any]:
    """计算评估结果汇总"""
    summary = {}

    for metric in metrics:
        values = [r.get(metric, 5) for r in results if metric in r]
        if values:
            summary[metric] = {
                "mean": statistics.mean(values),
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
                "std": statistics.stdev(values) if len(values) > 1 else 0,
            }

    # 计算总体得分
    all_means = [summary[m]["mean"] for m in metrics if m in summary]
    summary["overall_score"] = statistics.mean(all_means) if all_means else 0

    return summary