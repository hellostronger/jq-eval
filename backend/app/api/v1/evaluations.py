# 评估执行路由
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel

from ...core.database import get_db
from ...models import Evaluation, EvalResult, Dataset

router = APIRouter()


# Pydantic Schemas
class EvaluationCreate(BaseModel):
    name: str
    dataset_id: UUID
    config: Dict[str, Any]
    metrics: List[str]
    rag_system_ids: Optional[List[UUID]] = None


class EvaluationResponse(BaseModel):
    id: UUID
    name: str
    dataset_id: UUID
    status: str
    progress: int
    config: Dict[str, Any]
    metrics: List[str]

    class Config:
        from_attributes = True


class MetricConfigCreate(BaseModel):
    metric_id: UUID
    params: Dict[str, Any] = {}
    weight: float = 1.0
    enabled: bool = True


@router.post("", response_model=EvaluationResponse)
async def create_evaluation(
    data: EvaluationCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建评估任务"""
    # 检查数据集是否存在
    result = await db.execute(select(Dataset).where(Dataset.id == data.dataset_id))
    dataset = result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")

    evaluation = Evaluation(
        name=data.name,
        dataset_id=data.dataset_id,
        config=data.config,
        metrics=data.metrics,
        rag_system_ids=data.rag_system_ids or []
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

    # TODO: 触发Celery异步任务执行评估
    evaluation.status = "running"
    await db.commit()

    return {
        "message": "评估任务已启动",
        "eval_id": str(eval_id)
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
    """获取评估结果"""
    result = await db.execute(select(Evaluation).where(Evaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    results = await db.execute(
        select(EvalResult)
        .where(EvalResult.eval_id == eval_id)
        .offset(skip)
        .limit(limit)
    )

    return {
        "eval_id": str(eval_id),
        "summary": evaluation.summary,
        "results": [
            {
                "id": str(r.id),
                "qa_record_id": str(r.qa_record_id),
                "scores": r.scores
            }
            for r in results.scalars().all()
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