# 文档解释API路由
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
from datetime import datetime

from ...core.database import get_db
from ...core.utc_datetime import UTCDatetime
from ...models import DocExplanation, Document, Chunk

router = APIRouter()


# ---------- 全局文档API（供文档解释等场景使用，与数据集解耦） ----------

class GlobalDocumentResponse(BaseModel):
    """文档响应"""
    id: UUID
    title: Optional[str] = None
    content: Optional[str] = None
    file_type: Optional[str] = None
    source_type: Optional[str] = None
    chunk_count: int = 0

    class Config:
        from_attributes = True


class GlobalDocumentListResponse(BaseModel):
    """文档列表响应"""
    items: List[GlobalDocumentResponse]
    total: int


@router.get("/documents", response_model=GlobalDocumentListResponse)
async def list_all_documents(
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db)
):
    """获取所有文档列表（不分数据集）"""
    query = select(Document)
    count_query = select(func.count(Document.id))

    if search:
        like = f"%{search}%"
        query = query.where(Document.title.ilike(like))
        count_query = count_query.where(Document.title.ilike(like))

    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(Document.created_at.desc()).offset((page - 1) * size).limit(size)
    documents = (await db.execute(query)).scalars().all()

    # 批量查询chunk数量
    chunk_counts: dict = {}
    if documents:
        doc_ids = [d.id for d in documents]
        rows = await db.execute(
            select(Chunk.doc_id, func.count(Chunk.id))
            .where(Chunk.doc_id.in_(doc_ids))
            .group_by(Chunk.doc_id)
        )
        chunk_counts = {row[0]: row[1] for row in rows.all()}

    return GlobalDocumentListResponse(
        items=[GlobalDocumentResponse(
            id=d.id,
            title=d.title,
            content=d.content[:500] if d.content and len(d.content) > 500 else d.content,
            file_type=d.file_type,
            source_type=d.source_type,
            chunk_count=chunk_counts.get(d.id, 0),
        ) for d in documents],
        total=total,
    )


@router.post("/documents/upload", response_model=GlobalDocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    chunk_size: int = Query(500, ge=100, le=4000),
    chunk_overlap: int = Query(50, ge=0, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """上传文档（不关联数据集），自动分片"""
    file_content = await file.read()
    file_ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "txt"

    content = ""
    if file_ext in ("txt", "md"):
        content = file_content.decode("utf-8", errors="ignore")
    elif file_ext == "pdf":
        try:
            import fitz  # PyMuPDF
            pdf_doc = fitz.open(stream=file_content, filetype="pdf")
            content = "".join(page.get_text() for page in pdf_doc)
            pdf_doc.close()
        except ImportError:
            raise HTTPException(status_code=400, detail="PDF处理库未安装，请安装 PyMuPDF")
    else:
        content = file_content.decode("utf-8", errors="ignore")

    if not content.strip():
        raise HTTPException(status_code=400, detail="文档内容为空")

    document = await _create_document_with_chunks(
        db,
        title=file.filename or f"文档_{len(content)}字符",
        content=content,
        file_type=file_ext,
        source_type="upload",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        doc_metadata={"original_filename": file.filename, "size": len(file_content)},
    )

    return GlobalDocumentResponse(
        id=document.id,
        title=document.title,
        content=document.content[:500] if document.content and len(document.content) > 500 else document.content,
        file_type=document.file_type,
        source_type=document.source_type,
        chunk_count=await _count_chunks(db, document.id),
    )


class DocumentTextCreate(BaseModel):
    """从粘贴文本创建文档"""
    title: Optional[str] = None
    content: str
    chunk_size: int = 500
    chunk_overlap: int = 50


async def _create_document_with_chunks(db: AsyncSession, title: str, content: str,
                                 file_type: str, source_type: str,
                                 chunk_size: int, chunk_overlap: int,
                                 doc_metadata: Optional[dict] = None) -> Document:
    """创建文档并写入分片（upload 与 text 端点共用）"""
    from .datasets import _split_text

    document = Document(
        title=title,
        content=content,
        file_type=file_type,
        source_type=source_type,
        doc_metadata=doc_metadata or {}
    )
    db.add(document)
    await db.flush()

    chunks = _split_text(content, chunk_size, chunk_overlap)
    for i, chunk_text in enumerate(chunks):
        db.add(Chunk(
            doc_id=document.id,
            content=chunk_text["content"],
            chunk_index=i,
            start_char=chunk_text["start"],
            end_char=chunk_text["end"]
        ))

    await db.commit()
    await db.refresh(document)
    return document


@router.post("/documents/text", response_model=GlobalDocumentResponse)
async def create_document_from_text(
    data: DocumentTextCreate,
    db: AsyncSession = Depends(get_db)
):
    """从粘贴文本创建文档（自动分片）"""
    if not data.content.strip():
        raise HTTPException(status_code=400, detail="文本内容为空")

    document = await _create_document_with_chunks(
        db,
        title=data.title or f"文本_{len(data.content)}字符",
        content=data.content,
        file_type="txt",
        source_type="text_input",
        chunk_size=data.chunk_size,
        chunk_overlap=data.chunk_overlap,
    )

    return GlobalDocumentResponse(
        id=document.id,
        title=document.title,
        content=document.content[:500] if document.content and len(document.content) > 500 else document.content,
        file_type=document.file_type,
        source_type=document.source_type,
        chunk_count=await _count_chunks(db, document.id),
    )


async def _count_chunks(db: AsyncSession, doc_id) -> int:
    result = await db.execute(select(func.count(Chunk.id)).where(Chunk.doc_id == doc_id))
    return result.scalar() or 0


@router.get("/documents/{doc_id}", response_model=GlobalDocumentResponse)
async def get_document_detail(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取文档详情（全文，用于预览）"""
    document = await db.get(Document, doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")

    return GlobalDocumentResponse(
        id=document.id,
        title=document.title,
        content=document.content,
        file_type=document.file_type,
        source_type=document.source_type,
        chunk_count=await _count_chunks(db, document.id),
    )


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除文档（级联删除分片与文档解释）"""
    document = await db.get(Document, doc_id)
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")

    await db.delete(document)
    await db.commit()
    return {"message": "删除成功"}


# ---------- 文档解释API ----------


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
    created_at: Optional[UTCDatetime] = None

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
    created_at: Optional[UTCDatetime] = None


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