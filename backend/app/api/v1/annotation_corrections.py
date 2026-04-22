# 标注矫正API路由
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel

from ...core.database import get_db
from ...models import AnnotationCorrection, InvocationResult, QARecord, InvocationBatch, Model
from ...services.annotation_correction import create_correction_service

router = APIRouter()


# Pydantic Schemas
class SingleCorrectionRequest(BaseModel):
    """单条矫正请求"""
    invocation_result_id: UUID
    qa_record_id: UUID
    batch_id: Optional[UUID] = None
    llm_model_id: UUID


class BatchCorrectionRequest(BaseModel):
    """批量矫正请求"""
    llm_model_id: UUID


class CorrectionResponse(BaseModel):
    """矫正结果响应"""
    id: UUID
    invocation_result_id: Optional[UUID]
    qa_record_id: Optional[UUID]
    batch_id: Optional[UUID]
    status: str
    different_statements: List[dict] = []
    evidence_results: List[dict] = []
    is_doubtful: bool
    doubt_reason: Optional[str]
    is_confirmed: bool
    confirmed_at: Optional[datetime]
    summary: Optional[str]
    analysis_duration: Optional[str]
    error: Optional[str]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class CorrectionListResponse(BaseModel):
    """矫正结果列表响应"""
    items: List[CorrectionResponse]
    total: int
    doubtful_count: int


class ConfirmRequest(BaseModel):
    """确认请求"""
    is_doubtful: bool
    doubt_reason: Optional[str] = None


@router.post("/single", response_model=CorrectionResponse)
async def analyze_single(
    data: SingleCorrectionRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """分析单条QA数据的差异"""
    # 验证LLM模型
    model_result = await db.execute(select(Model).where(Model.id == data.llm_model_id))
    llm_model = model_result.scalar_one_or_none()
    if not llm_model or llm_model.model_type != "llm":
        raise HTTPException(status_code=400, detail="LLM模型不存在或类型错误")

    # 验证调用结果
    result_query = await db.execute(
        select(InvocationResult).where(InvocationResult.id == data.invocation_result_id)
    )
    invocation_result = result_query.scalar_one_or_none()
    if not invocation_result:
        raise HTTPException(status_code=404, detail="调用结果不存在")

    # 验证QA记录
    qa_query = await db.execute(
        select(QARecord).where(QARecord.id == data.qa_record_id)
    )
    qa_record = qa_query.scalar_one_or_none()
    if not qa_record:
        raise HTTPException(status_code=404, detail="QA记录不存在")

    # 执行分析
    service = await create_correction_service(db, data.llm_model_id)
    correction = await service.analyze_single(
        invocation_result_id=data.invocation_result_id,
        qa_record_id=data.qa_record_id,
        batch_id=data.batch_id,
    )

    return correction


@router.post("/batch/{batch_id}", response_model=CorrectionListResponse)
async def analyze_batch(
    batch_id: UUID,
    data: BatchCorrectionRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """批量分析一个批次的所有QA数据"""
    # 验证LLM模型
    model_result = await db.execute(select(Model).where(Model.id == data.llm_model_id))
    llm_model = model_result.scalar_one_or_none()
    if not llm_model or llm_model.model_type != "llm":
        raise HTTPException(status_code=400, detail="LLM模型不存在或类型错误")

    # 验证批次
    batch_query = await db.execute(
        select(InvocationBatch).where(InvocationBatch.id == batch_id)
    )
    batch = batch_query.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")

    # 执行批量分析
    service = await create_correction_service(db, data.llm_model_id)
    corrections = await service.analyze_batch(batch_id)

    # 统计存疑数量
    doubtful_count = sum(1 for c in corrections if c.is_doubtful)

    return CorrectionListResponse(
        items=corrections,
        total=len(corrections),
        doubtful_count=doubtful_count,
    )


@router.get("/{correction_id}", response_model=CorrectionResponse)
async def get_correction(
    correction_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """获取矫正结果详情"""
    result = await db.execute(
        select(AnnotationCorrection).where(AnnotationCorrection.id == correction_id)
    )
    correction = result.scalar_one_or_none()
    if not correction:
        raise HTTPException(status_code=404, detail="矫正结果不存在")
    return correction


@router.get("/batch/{batch_id}", response_model=CorrectionListResponse)
async def list_batch_corrections(
    batch_id: UUID,
    status: Optional[str] = None,
    is_doubtful: Optional[bool] = None,
    page: int = 1,
    size: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """获取批次的矫正结果列表"""
    # 构建查询
    query = select(AnnotationCorrection).where(AnnotationCorrection.batch_id == batch_id)

    if status:
        query = query.where(AnnotationCorrection.status == status)
    if is_doubtful is not None:
        query = query.where(AnnotationCorrection.is_doubtful == is_doubtful)

    # 统计总数
    total_query = select(func.count(AnnotationCorrection.id)).where(
        AnnotationCorrection.batch_id == batch_id
    )
    if status:
        total_query = total_query.where(AnnotationCorrection.status == status)
    if is_doubtful is not None:
        total_query = total_query.where(AnnotationCorrection.is_doubtful == is_doubtful)
    total_result = await db.execute(total_query)
    total = total_result.scalar() or 0

    # 统计存疑数
    doubtful_query = select(func.count(AnnotationCorrection.id)).where(
        AnnotationCorrection.batch_id == batch_id,
        AnnotationCorrection.is_doubtful == True,
    )
    doubtful_result = await db.execute(doubtful_query)
    doubtful_count = doubtful_result.scalar() or 0

    # 分页查询
    skip = (page - 1) * size
    query = query.offset(skip).limit(size).order_by(AnnotationCorrection.created_at.desc())
    result = await db.execute(query)
    corrections = result.scalars().all()

    return CorrectionListResponse(
        items=corrections,
        total=total,
        doubtful_count=doubtful_count,
    )


@router.get("/invocation/{invocation_result_id}", response_model=CorrectionResponse)
async def get_correction_by_invocation(
    invocation_result_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """根据调用结果ID获取矫正结果"""
    result = await db.execute(
        select(AnnotationCorrection)
        .where(AnnotationCorrection.invocation_result_id == invocation_result_id)
        .order_by(AnnotationCorrection.created_at.desc())
        .limit(1)
    )
    correction = result.scalar_one_or_none()
    if not correction:
        raise HTTPException(status_code=404, detail="未找到该调用结果的矫正记录")
    return correction


@router.put("/{correction_id}/confirm")
async def confirm_correction(
    correction_id: UUID,
    data: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """用户确认存疑标记"""
    result = await db.execute(
        select(AnnotationCorrection).where(AnnotationCorrection.id == correction_id)
    )
    correction = result.scalar_one_or_none()
    if not correction:
        raise HTTPException(status_code=404, detail="矫正结果不存在")

    correction.is_confirmed = True
    correction.confirmed_at = datetime.utcnow()
    correction.is_doubtful = data.is_doubtful
    if data.doubt_reason:
        correction.doubt_reason = data.doubt_reason

    await db.commit()

    return {"message": "确认成功", "correction_id": str(correction_id)}