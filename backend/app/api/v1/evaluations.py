# 评估执行路由
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel
from celery.result import AsyncResult

from ...core.database import get_db
from ...core.config import settings
from ...core.celery_app import celery_app
from ...models import Evaluation, EvalResult, Dataset, QARecord
from ...tasks.evaluation_tasks import evaluation_task

router = APIRouter()


# Pydantic Schemas
class EvaluationCreate(BaseModel):
    name: str
    description: Optional[str] = None
    dataset_id: Optional[UUID] = None  # 可选，如果选择调用批次可从中获取
    rag_system_id: Optional[UUID] = None
    llm_model_id: Optional[UUID] = None
    embedding_model_id: Optional[UUID] = None
    metrics: List[str]
    batch_size: Optional[int] = 10
    invocation_batch_id: Optional[UUID] = None  # 关联的调用批次
    reuse_invocation: Optional[bool] = False  # 是否复用存量调用结果


class EvaluationResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    dataset_id: Optional[UUID]
    rag_system_id: Optional[UUID]
    llm_model_id: Optional[UUID]
    embedding_model_id: Optional[UUID]
    invocation_batch_id: Optional[UUID] = None
    reuse_invocation: Optional[bool] = False
    metrics: List[str]
    batch_size: int
    status: str
    progress: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    summary: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MetricConfigCreate(BaseModel):
    metric_id: UUID
    params: Dict[str, Any] = {}
    weight: float = 1.0
    enabled: bool = True


class CompareRequest(BaseModel):
    eval_ids: List[UUID]


@router.post("/compare")
async def compare_evaluations(
    data: CompareRequest,
    db: AsyncSession = Depends(get_db)
):
    """对比多个评估任务的结果

    Args:
        data: 包含要对比的评估任务ID列表

    Returns:
        包含评估任务信息、对比结果和汇总统计
    """
    if len(data.eval_ids) < 2:
        raise HTTPException(status_code=400, detail="至少需要选择2个评估任务进行对比")

    # 获取所有评估任务
    evaluations = []
    for eval_id in data.eval_ids:
        result = await db.execute(select(Evaluation).where(Evaluation.id == eval_id))
        evaluation = result.scalar_one_or_none()
        if not evaluation:
            raise HTTPException(status_code=404, detail=f"评估任务 {eval_id} 不存在")
        if evaluation.status != "completed":
            raise HTTPException(status_code=400, detail=f"评估任务 {eval_id} 未完成，无法对比")
        evaluations.append(evaluation)

    # 按评估任务名称建立映射
    eval_map = {str(e.id): e.name for e in evaluations}

    # 获取所有评估结果，按 qa_record_id 组织
    all_results = {}
    for evaluation in evaluations:
        results = await db.execute(
            select(EvalResult, QARecord)
            .join(QARecord, EvalResult.qa_record_id == QARecord.id)
            .where(EvalResult.eval_id == evaluation.id)
        )
        for er, qr in results.all():
            qa_id = str(qr.id)
            if qa_id not in all_results:
                all_results[qa_id] = {
                    "qa_record_id": qa_id,
                    "question": qr.question,
                    "ground_truth": qr.ground_truth,
                    "scores": {}
                }
            all_results[qa_id]["scores"][evaluation.name] = er.scores or {}

    # 构建对比数据
    comparison_data = list(all_results.values())

    # 构建汇总数据
    summary_data = {}
    for evaluation in evaluations:
        summary_data[evaluation.name] = evaluation.summary or {}

    return {
        "evaluations": [
            {
                "id": str(e.id),
                "name": e.name,
                "metrics": e.metrics or [],
                "summary": e.summary,
            }
            for e in evaluations
        ],
        "comparison": comparison_data,
        "summary": summary_data,
    }


@router.post("", response_model=EvaluationResponse)
async def create_evaluation(
    data: EvaluationCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建评估任务"""
    # 确定数据集ID：优先使用传入的，否则从调用批次获取
    dataset_id = data.dataset_id

    # 如果指定了调用批次，检查是否存在并获取数据集
    if data.invocation_batch_id:
        from ...models import InvocationBatch
        result = await db.execute(select(InvocationBatch).where(InvocationBatch.id == data.invocation_batch_id))
        batch = result.scalar_one_or_none()
        if not batch:
            raise HTTPException(status_code=404, detail="调用批次不存在")
        if batch.status != "completed":
            raise HTTPException(status_code=400, detail="调用批次尚未完成，无法用于评估")
        # 如果没有指定数据集，使用调用批次的数据集
        if not dataset_id:
            dataset_id = batch.dataset_id

    # 数据集ID必须存在
    if not dataset_id:
        raise HTTPException(status_code=400, detail="必须指定数据集或选择已完成的调用批次")

    # 检查数据集是否存在
    result = await db.execute(select(Dataset).where(Dataset.id == dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    evaluation = Evaluation(
        name=data.name,
        description=data.description,
        dataset_id=dataset_id,
        rag_system_id=data.rag_system_id,
        llm_model_id=data.llm_model_id,
        embedding_model_id=data.embedding_model_id,
        metrics=data.metrics,
        batch_size=data.batch_size or 10,
        invocation_batch_id=data.invocation_batch_id,
        reuse_invocation=data.reuse_invocation or False,
    )
    db.add(evaluation)
    await db.commit()
    await db.refresh(evaluation)
    return evaluation


@router.get("", response_model=List[EvaluationResponse])
async def list_evaluations(
    status: Optional[str] = None,
    dataset_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取评估任务列表"""
    query = select(Evaluation)
    if status:
        query = query.where(Evaluation.status == status)
    if dataset_id:
        query = query.where(Evaluation.dataset_id == dataset_id)
    result = await db.execute(query.order_by(Evaluation.created_at.desc()))
    return result.scalars().all()


@router.get("/{eval_id}", response_model=EvaluationResponse)
async def get_evaluation(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取评估任务详情"""
    result = await db.execute(select(Evaluation).where(Evaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")
    return evaluation


@router.delete("/{eval_id}")
async def delete_evaluation(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除评估任务"""
    result = await db.execute(select(Evaluation).where(Evaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    await db.delete(evaluation)
    await db.commit()
    return {"message": "删除成功"}


@router.post("/{eval_id}/run")
async def run_evaluation(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """执行评估任务"""
    result = await db.execute(select(Evaluation).where(Evaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    if evaluation.status == "running":
        raise HTTPException(status_code=400, detail="评估任务正在执行中")

    # 更新状态为运行中
    evaluation.status = "running"
    await db.commit()

    # 提交 Celery 异步任务
    task = evaluation_task.delay(str(eval_id))

    return {
        "message": "评估任务已启动",
        "eval_id": str(eval_id),
        "task_id": task.id
    }


@router.get("/{eval_id}/status")
async def get_evaluation_status(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取评估任务状态"""
    result = await db.execute(select(Evaluation).where(Evaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    return {
        "eval_id": str(eval_id),
        "status": evaluation.status,
        "progress": evaluation.progress,
        "error": evaluation.error
    }


@router.get("/{eval_id}/results")
async def get_evaluation_results(
    eval_id: UUID,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """获取评估结果，包含每条 QA 记录的详细信息和得分"""
    result = await db.execute(select(Evaluation).where(Evaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    # JOIN QARecord 表获取问题内容
    results = await db.execute(
        select(EvalResult, QARecord)
        .join(QARecord, EvalResult.qa_record_id == QARecord.id)
        .where(EvalResult.eval_id == eval_id)
        .offset(skip)
        .limit(limit)
    )

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
                "metric_scores": er.scores,
                "details": er.details,
                "created_at": er.created_at.isoformat() if er.created_at else None,
            }
            for er, qr in results.all()
        ]
    }


@router.get("/{eval_id}/analysis")
async def get_analysis(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取根因分析"""
    result = await db.execute(select(Evaluation).where(Evaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    if evaluation.status != "completed":
        raise HTTPException(status_code=400, detail="评估任务尚未完成")

    # TODO: 实现根因分析逻辑
    return {
        "eval_id": str(eval_id),
        "analysis": {
            "retrieval_analysis": {},
            "generation_analysis": {},
            "recommendations": []
        }
    }


@router.get("/{eval_id}/export")
async def export_report(
    eval_id: UUID,
    format: str = "json",
    db: AsyncSession = Depends(get_db)
):
    """导出评估报告"""
    result = await db.execute(select(Evaluation).where(Evaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    # TODO: 实现报告导出逻辑
    return {
        "message": "报告导出功能开发中",
        "eval_id": str(eval_id),
        "format": format
    }


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """获取 Celery 任务状态（从 Redis 查询）

    Args:
        task_id: Celery 任务ID

    Returns:
        任务状态信息，包括：
        - task_id: 任务ID
        - status: 任务状态 (PENDING/STARTED/PROGRESS/SUCCESS/FAILURE)
        - result: 任务结果（任务完成时）
        - error: 错误信息（任务失败时）
        - progress: 进度信息（任务进行中时）
    """
    task_result = AsyncResult(task_id, app=celery_app)

    response = {
        "task_id": task_id,
        "status": task_result.status,
    }

    if task_result.ready():
        # 任务已完成（成功或失败）
        if task_result.successful():
            response["result"] = task_result.result
        else:
            response["error"] = str(task_result.result)
    elif task_result.status == "PROGRESS":
        # 任务进行中，有进度信息
        info = task_result.info or {}
        response["progress"] = info.get("progress", 0)
        response["current"] = info.get("current", 0)
        response["total"] = info.get("total", 0)

    return response


@router.post("/{eval_id}/cancel")
async def cancel_evaluation(
    eval_id: UUID,
    task_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """取消评估任务

    Args:
        eval_id: 评估任务ID
        task_id: Celery 任务ID（可选，如果不提供则尝试从数据库获取最近的任务）
    """
    result = await db.execute(select(Evaluation).where(Evaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    if evaluation.status != "running":
        raise HTTPException(status_code=400, detail="评估任务未在运行中，无法取消")

    if task_id:
        # 取消指定的 Celery 任务
        celery_app.control.revoke(task_id, terminate=True, signal='SIGKILL')

    # 更新评估状态
    evaluation.status = "failed"
    evaluation.error = "任务已被用户取消"
    await db.commit()

    return {
        "message": "评估任务已取消",
        "eval_id": str(eval_id)
    }


@router.post("/{eval_id}/retry")
async def retry_evaluation(
    eval_id: UUID,
    reuse_invocation: bool = True,  # 默认复用存量调用结果
    db: AsyncSession = Depends(get_db)
):
    """重试评估任务

    只允许对 failed 状态的任务进行重试。
    重试时会清除之前的错误信息和结果，重新启动评估。

    Args:
        eval_id: 评估任务ID
        reuse_invocation: 是否复用存量调用结果（默认True）
    """
    result = await db.execute(select(Evaluation).where(Evaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    # 只允许重试失败的任务
    if evaluation.status not in ("failed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"只有失败或取消的任务才能重试，当前状态: {evaluation.status}"
        )

    # 更新 reuse_invocation 设置
    evaluation.reuse_invocation = reuse_invocation

    # 清除之前的错误信息和时间，重置状态
    evaluation.status = "pending"
    evaluation.error = None
    evaluation.started_at = None
    evaluation.completed_at = None
    evaluation.progress = 0

    # 删除之前的评估结果（如果需要重新评估）
    from sqlalchemy import delete
    await db.execute(delete(EvalResult).where(EvalResult.eval_id == eval_id))

    await db.commit()

    # 启动新的评估任务
    task = evaluation_task.delay(str(eval_id))

    # 更新状态为运行中
    evaluation.status = "running"
    await db.commit()

    return {
        "message": "评估任务已重新启动",
        "eval_id": str(eval_id),
        "task_id": task.id,
        "reuse_invocation": reuse_invocation
    }