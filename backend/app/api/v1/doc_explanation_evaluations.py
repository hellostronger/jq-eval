# 文档解释评估API路由
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel
from datetime import datetime

from ...core.database import get_db
from ...models import DocExplanationEvaluation, DocExplanationEvalResult, DocExplanation, Document, Model

router = APIRouter()


class DocExplanationEvalCreate(BaseModel):
    name: str
    description: Optional[str] = None
    llm_model_id: UUID
    dataset_id: Optional[UUID] = None
    doc_ids: Optional[List[UUID]] = None
    metrics: Optional[List[str]] = ["completeness", "accuracy", "info_missing", "explanation_error"]
    batch_size: Optional[int] = 10


class DocExplanationEvalResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    llm_model_id: UUID
    dataset_id: Optional[UUID] = None
    doc_ids: Optional[List[UUID]] = None
    metrics: List[str]
    batch_size: int
    status: str
    progress: int
    error: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DocExplanationEvalResultResponse(BaseModel):
    id: UUID
    eval_id: UUID
    doc_id: UUID
    explanation_id: UUID
    document_title: Optional[str] = None
    document_content: Optional[str] = None
    explanation: Optional[str] = None
    scores: Dict[str, Any]
    details: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None


@router.post("", response_model=DocExplanationEvalResponse)
async def create_doc_explanation_evaluation(
    data: DocExplanationEvalCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建文档解释评估任务"""
    result = await db.execute(select(Model).where(Model.id == data.llm_model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")

    evaluation = DocExplanationEvaluation(
        name=data.name,
        description=data.description,
        llm_model_id=data.llm_model_id,
        dataset_id=data.dataset_id,
        doc_ids=data.doc_ids,
        metrics=data.metrics or ["completeness", "accuracy", "info_missing", "explanation_error"],
        batch_size=data.batch_size or 10,
    )
    db.add(evaluation)
    await db.commit()
    await db.refresh(evaluation)
    return evaluation


@router.get("", response_model=List[DocExplanationEvalResponse])
async def list_doc_explanation_evaluations(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取文档解释评估任务列表"""
    query = select(DocExplanationEvaluation)
    if status:
        query = query.where(DocExplanationEvaluation.status == status)
    query = query.order_by(DocExplanationEvaluation.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{eval_id}", response_model=DocExplanationEvalResponse)
async def get_doc_explanation_evaluation(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取文档解释评估任务详情"""
    result = await db.execute(select(DocExplanationEvaluation).where(DocExplanationEvaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")
    return evaluation


@router.post("/{eval_id}/run")
async def run_doc_explanation_evaluation(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """启动文档解释评估任务"""
    result = await db.execute(select(DocExplanationEvaluation).where(DocExplanationEvaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    if evaluation.status == "running":
        raise HTTPException(status_code=400, detail="任务正在执行中")

    evaluation.status = "running"
    await db.commit()

    from ...tasks.doc_explanation_tasks import doc_explanation_eval_task
    task = doc_explanation_eval_task.delay(str(eval_id))

    return {
        "message": "评估任务已启动",
        "eval_id": str(eval_id),
        "task_id": task.id
    }


@router.get("/{eval_id}/results", response_model=List[DocExplanationEvalResultResponse])
async def get_doc_explanation_eval_results(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取文档解释评估结果"""
    result = await db.execute(select(DocExplanationEvaluation).where(DocExplanationEvaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    results = await db.execute(
        select(DocExplanationEvalResult, DocExplanation, Document)
        .join(DocExplanation, DocExplanationEvalResult.explanation_id == DocExplanation.id)
        .join(Document, DocExplanationEvalResult.doc_id == Document.id)
        .where(DocExplanationEvalResult.eval_id == eval_id)
    )

    return [
        DocExplanationEvalResultResponse(
            id=r.id,
            eval_id=r.eval_id,
            doc_id=r.doc_id,
            explanation_id=r.explanation_id,
            document_title=doc.title,
            document_content=doc.content[:500] if doc.content else None,
            explanation=exp.explanation[:500] if exp.explanation else None,
            scores=r.scores,
            details=r.details,
            created_at=r.created_at,
        )
        for r, exp, doc in results.all()
    ]


@router.delete("/{eval_id}")
async def delete_doc_explanation_evaluation(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除文档解释评估任务"""
    result = await db.execute(select(DocExplanationEvaluation).where(DocExplanationEvaluation.id == eval_id))
    evaluation = result.scalar_one_or_none()
    if not evaluation:
        raise HTTPException(status_code=404, detail="评估任务不存在")

    if evaluation.status == "running":
        raise HTTPException(status_code=400, detail="运行中的任务无法删除")

    await db.delete(evaluation)
    await db.commit()
    return {"message": "删除成功"}