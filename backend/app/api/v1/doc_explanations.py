# 文档解释API路由
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
from datetime import datetime

from ...core.database import get_db
from ...models import DocExplanation, Document

router = APIRouter()


class DocExplanationCreate(BaseModel):
    doc_id: UUID
    explanation: str
    source: Optional[str] = "manual"


class DocExplanationBatchCreate(BaseModel):
    explanations: List[DocExplanationCreate]


class DocExplanationUpdate(BaseModel):
    explanation: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None


class DocExplanationResponse(BaseModel):
    id: UUID
    doc_id: UUID
    explanation: str
    source: str
    status: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DocExplanationWithDocument(BaseModel):
    id: UUID
    doc_id: UUID
    explanation: str
    source: str
    status: str
    document_title: Optional[str] = None
    document_content: Optional[str] = None
    created_at: Optional[datetime] = None


@router.post("", response_model=DocExplanationResponse)
async def create_doc_explanation(
    data: DocExplanationCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建文档解释"""
    result = await db.execute(select(Document).where(Document.id == data.doc_id))
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")

    explanation = DocExplanation(
        doc_id=data.doc_id,
        explanation=data.explanation,
        source=data.source or "manual",
    )
    db.add(explanation)
    await db.commit()
    await db.refresh(explanation)
    return explanation


@router.post("/batch", response_model=List[DocExplanationResponse])
async def create_doc_explanations_batch(
    data: DocExplanationBatchCreate,
    db: AsyncSession = Depends(get_db)
):
    """批量创建文档解释"""
    explanations = []
    for item in data.explanations:
        result = await db.execute(select(Document).where(Document.id == item.doc_id))
        document = result.scalar_one_or_none()
        if not document:
            continue

        explanation = DocExplanation(
            doc_id=item.doc_id,
            explanation=item.explanation,
            source=item.source or "manual",
        )
        db.add(explanation)
        explanations.append(explanation)

    await db.commit()
    return explanations


@router.get("", response_model=List[DocExplanationWithDocument])
async def list_doc_explanations(
    doc_id: Optional[UUID] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取文档解释列表"""
    query = select(DocExplanation, Document).join(
        Document, DocExplanation.doc_id == Document.id
    )
    if doc_id:
        query = query.where(DocExplanation.doc_id == doc_id)
    if status:
        query = query.where(DocExplanation.status == status)

    query = query.order_by(DocExplanation.created_at.desc())
    result = await db.execute(query)

    return [
        DocExplanationWithDocument(
            id=exp.id,
            doc_id=exp.doc_id,
            explanation=exp.explanation,
            source=exp.source,
            status=exp.status,
            document_title=doc.title,
            document_content=doc.content[:500] if doc.content else None,
            created_at=exp.created_at,
        )
        for exp, doc in result.all()
    ]


@router.get("/{exp_id}", response_model=DocExplanationWithDocument)
async def get_doc_explanation(
    exp_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取文档解释详情"""
    result = await db.execute(
        select(DocExplanation, Document)
        .join(Document, DocExplanation.doc_id == Document.id)
        .where(DocExplanation.id == exp_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="文档解释不存在")

    exp, doc = row
    return DocExplanationWithDocument(
        id=exp.id,
        doc_id=exp.doc_id,
        explanation=exp.explanation,
        source=exp.source,
        status=exp.status,
        document_title=doc.title,
        document_content=doc.content,
        created_at=exp.created_at,
    )


@router.put("/{exp_id}", response_model=DocExplanationResponse)
async def update_doc_explanation(
    exp_id: UUID,
    data: DocExplanationUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新文档解释"""
    result = await db.execute(select(DocExplanation).where(DocExplanation.id == exp_id))
    explanation = result.scalar_one_or_none()
    if not explanation:
        raise HTTPException(status_code=404, detail="文档解释不存在")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(explanation, key, value)

    await db.commit()
    await db.refresh(explanation)
    return explanation


@router.delete("/{exp_id}")
async def delete_doc_explanation(
    exp_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除文档解释"""
    result = await db.execute(select(DocExplanation).where(DocExplanation.id == exp_id))
    explanation = result.scalar_one_or_none()
    if not explanation:
        raise HTTPException(status_code=404, detail="文档解释不存在")

    await db.delete(explanation)
    await db.commit()
    return {"message": "删除成功"}