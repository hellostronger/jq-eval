# 训练数据评估 API 路由
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel
from celery.result import AsyncResult

from ...core.database import get_db
from ...core.config import settings
from ...core.celery_app import celery_app
from ...models import (
    TrainingDataEval,
    TrainingDataMetricConfig,
    TrainingDataEvalResult,
    TrainingQualityChecker,
    TrainingDataTemplate,
    Dataset,
    QARecord
)
from ...services.training_data.engine import TrainingDataMetricEngine, TRAINING_DATA_METRIC_REGISTRY

router = APIRouter()


# Pydantic Schemas
class MetricConfigCreate(BaseModel):
    metric_name: str
    metric_type: str
    params: Dict[str, Any] = {}
    weight: float = 1.0
    enabled: bool = True
    threshold: Optional[float] = None
    threshold_type: Optional[str] = None


class TrainingDataEvalCreate(BaseModel):
    name: str
    description: Optional[str] = None
    dataset_id: UUID
    data_type: str  # llm/embedding/reranker/reward_model/dpo/vlm/vla
    config: Dict[str, Any] = {}
    metrics: List[str]
    metric_configs: List[MetricConfigCreate] = []


class TrainingDataEvalResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    dataset_id: UUID
    data_type: str
    config: Dict[str, Any]
    metrics: List[str]
    status: str
    progress: int
    total_samples: int
    passed_samples: int
    failed_samples: int
    pass_rate: float
    summary: Optional[Dict[str, Any]]
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TrainingDataEvalResultResponse(BaseModel):
    id: UUID
    eval_id: UUID
    qa_record_id: UUID
    question: Optional[str]
    answer: Optional[str]
    scores: Dict[str, Any]
    quality_tags: List[str]
    issues: List[str]
    suggestions: List[str]
    status: str
    overall_score: float
    created_at: Optional[datetime] = None


@router.post("", response_model=TrainingDataEvalResponse)
async def create_training_data_eval(
    data: TrainingDataEvalCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建训练数据评估任务"""
    # 检查数据集是否存在
    result = await db.execute(select(Dataset).where(Dataset.id == data.dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    evaluation = TrainingDataEval(
        name=data.name,
        description=data.description,
        dataset_id=data.dataset_id,
        data_type=data.data_type,
        config=data.config,
        metrics=data.metrics,
        status="pending",
        progress=0
    )
    db.add(evaluation)
    await db.commit()
    await db.refresh(evaluation)

    # 创建指标配置
    for config in data.metric_configs:
        metric_config = TrainingDataMetricConfig(
            eval_id=evaluation.id,
            metric_name=config.metric_name,
            metric_type=config.metric_type,
            params=config.params,
            weight=config.weight,
            enabled=config.enabled,
            threshold=config.threshold,
            threshold_type=config.threshold_type
        )
        db.add(metric_config)

    await db.commit()
    await db.refresh(evaluation)
    return evaluation


@router.get("", response_model=List[TrainingDataEvalResponse])
async def list_training_data_evals(
    status: Optional[str] = None,
    dataset_id: Optional[UUID] = None,
    data_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取训练数据评估任务列表"""
    query = select(TrainingDataEval)
    if status:
        query = query.where(TrainingDataEval.status == status)
    if dataset_id:
        query = query.where(TrainingDataEval.dataset_id == dataset_id)
    if data_type:
        query = query.where(TrainingDataEval.data_type == data_type)
    result = await db.execute(query.order_by(TrainingDataEval.created_at.desc()))
    return result.scalars().all()


@router.get("/{eval_id}", response_model=TrainingDataEvalResponse)
async def get_training_data_eval(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取训练数据评估任务详情"""
    result = await db.execute(select(TrainingDataEval).where(TrainingDataEval.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")
    return evaluation


@router.delete("/{eval_id}")
async def delete_training_data_eval(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除训练数据评估任务"""
    result = await db.execute(select(TrainingDataEval).where(TrainingDataEval.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    await db.delete(evaluation)
    await db.commit()
    return {"message": "删除成功"}


@router.post("/{eval_id}/run")
async def run_training_data_eval(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """执行训练数据评估任务"""
    result = await db.execute(select(TrainingDataEval).where(TrainingDataEval.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    if evaluation.status == "running":
        raise HTTPException(status_code=400, detail="评估任务正在执行中")

    # 更新状态为运行中
    evaluation.status = "running"
    evaluation.started_at = datetime.utcnow()
    await db.commit()

    # 提交 Celery 异步任务
    from ...tasks.training_data_eval_tasks import training_data_eval_task
    task = training_data_eval_task.delay(str(eval_id))

    return {
        "message": "评估任务已启动",
        "eval_id": str(eval_id),
        "task_id": task.id
    }


@router.get("/{eval_id}/status")
async def get_training_data_eval_status(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取训练数据评估任务状态"""
    result = await db.execute(select(TrainingDataEval).where(TrainingDataEval.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    return {
        "eval_id": str(eval_id),
        "status": evaluation.status,
        "progress": evaluation.progress,
        "total_samples": evaluation.total_samples,
        "passed_samples": evaluation.passed_samples,
        "failed_samples": evaluation.failed_samples,
        "pass_rate": evaluation.pass_rate,
        "error": evaluation.error
    }


@router.get("/{eval_id}/results")
async def get_training_data_eval_results(
    eval_id: UUID,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """获取训练数据评估结果"""
    result = await db.execute(select(TrainingDataEval).where(TrainingDataEval.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    # 构建查询
    query = select(TrainingDataEvalResult, QARecord).join(
        QARecord, TrainingDataEvalResult.qa_record_id == QARecord.id
    ).where(TrainingDataEvalResult.eval_id == eval_id)

    if status:
        query = query.where(TrainingDataEvalResult.status == status)

    # 分页查询
    results = await db.execute(query.offset(skip).limit(limit))

    return {
        "eval_id": str(eval_id),
        "summary": evaluation.summary,
        "results": [
            {
                "id": str(er.id),
                "qa_record_id": str(er.qa_record_id),
                "question": qr.question,
                "answer": qr.answer,
                "ground_truth": qr.ground_truth,
                "scores": er.scores,
                "details": er.details,
                "quality_tags": er.quality_tags,
                "issues": er.issues,
                "suggestions": er.suggestions,
                "status": er.status,
                "overall_score": er.overall_score,
                "created_at": er.created_at.isoformat() if er.created_at else None,
            }
            for er, qr in results.all()
        ]
    }


@router.get("/metrics/available")
async def get_available_metrics(
    data_type: Optional[str] = None
):
    """获取可用的训练数据评估指标"""
    metrics = []
    for name, metric_class in TRAINING_DATA_METRIC_REGISTRY.items():
        if data_type is None or data_type in metric_class.data_types:
            metrics.append(metric_class.get_info(metric_class()))
    return {"metrics": metrics}


@router.get("/templates")
async def get_training_data_templates(
    data_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取训练数据评估模板"""
    query = select(TrainingDataTemplate).where(TrainingDataTemplate.is_enabled == True)
    if data_type:
        query = query.where(TrainingDataTemplate.data_type == data_type)
    result = await db.execute(query.order_by(TrainingDataTemplate.sort_order))
    templates = result.scalars().all()
    return {
        "templates": [
            {
                "id": str(t.id),
                "name": t.name,
                "display_name": t.display_name,
                "data_type": t.data_type,
                "description": t.description,
                "metric_configs": t.metric_configs,
                "default_thresholds": t.default_thresholds,
                "is_builtin": t.is_builtin,
            }
            for t in templates
        ]
    }


@router.get("/quality-rules")
async def get_quality_rules(
    data_type: Optional[str] = None,
    rule_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取质量检查规则"""
    query = select(TrainingQualityChecker).where(TrainingQualityChecker.is_enabled == True)
    if data_type:
        query = query.where(TrainingQualityChecker.data_types.contains([data_type]))
    if rule_type:
        query = query.where(TrainingQualityChecker.rule_type == rule_type)
    result = await db.execute(query)
    rules = result.scalars().all()
    return {
        "rules": [
            {
                "id": str(r.id),
                "name": r.name,
                "description": r.description,
                "data_types": r.data_types,
                "rule_type": r.rule_type,
                "config": r.config,
                "threshold_min": r.threshold_min,
                "threshold_max": r.threshold_max,
                "severity": r.severity,
                "auto_fixable": r.auto_fixable,
                "is_builtin": r.is_builtin,
            }
            for r in rules
        ]
    }


@router.get("/{eval_id}/export")
async def export_training_data_eval_report(
    eval_id: UUID,
    format: str = "json",
    db: AsyncSession = Depends(get_db)
):
    """导出训练数据评估报告"""
    result = await db.execute(select(TrainingDataEval).where(TrainingDataEval.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    # 获取评估结果
    results = await db.execute(
        select(TrainingDataEvalResult, QARecord).join(
            QARecord, TrainingDataEvalResult.qa_record_id == QARecord.id
        ).where(TrainingDataEvalResult.eval_id == eval_id)
    )

    report = {
        "eval_id": str(eval_id),
        "name": evaluation.name,
        "data_type": evaluation.data_type,
        "summary": evaluation.summary,
        "total_samples": evaluation.total_samples,
        "passed_samples": evaluation.passed_samples,
        "failed_samples": evaluation.failed_samples,
        "pass_rate": evaluation.pass_rate,
        "quality_distribution": evaluation.quality_distribution,
        "details": [
            {
                "question": qr.question,
                "answer": qr.answer,
                "scores": er.scores,
                "status": er.status,
                "quality_tags": er.quality_tags,
                "issues": er.issues,
                "suggestions": er.suggestions,
            }
            for er, qr in results.all()
        ]
    }

    if format == "json":
        return report
    elif format == "csv":
        # TODO: 实现 CSV 导出
        return {"message": "CSV导出功能开发中", "report": report}
    else:
        raise HTTPException(status_code=400, detail="不支持的导出格式")
