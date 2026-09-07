# 文档解析Celery任务：批量调用 minerU 等解析服务，产物写入 Document+Chunk
import asyncio
import time
from typing import Dict, List, Any
from datetime import datetime
from uuid import UUID
import logging

from app.core.celery_app import celery_app
from app.core.database import get_db_context
from app.models import DocParseBatch, DocParseResult, Document, Model
from app.services.doc_parser import (
    parse_batch_mineru_official,
    parse_document_with_model,
    DocParseError,
)
from app.services.storage.minio_service import get_minio_service
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


@celery_app.task(bind=True, name="doc_parse_task",
                 soft_time_limit=110 * 60, time_limit=115 * 60)
def doc_parse_task(self, batch_id: str) -> Dict[str, Any]:
    """执行文档解析批次任务

    Args:
        batch_id: 解析批次ID (UUID字符串格式)
    """
    return run_async(_run_doc_parse_task(self, UUID(batch_id)))


async def _load_file(minio, object_name: str) -> bytes:
    """从 MinIO documents bucket 读取源文件"""
    result = await minio.download_file(bucket="documents", object_name=object_name)
    if not result.get("success"):
        raise DocParseError(result.get("error") or "源文件下载失败")
    return result["data"]


async def _save_document(db, batch: DocParseBatch, file_name: str, md_content: str) -> Document:
    """把解析出的 Markdown 写入 Document+Chunk（source_type=mineru）"""
    from app.api.v1.datasets import _split_text

    document = Document(
        title=file_name.rsplit(".", 1)[0] if "." in file_name else file_name,
        content=md_content,
        file_type="md",
        source_type="mineru",
        doc_metadata={
            "original_filename": file_name,
            "parse_batch_id": str(batch.id),
            "parser_model": batch.parser_model_name,
        },
    )
    db.add(document)
    await db.flush()

    for i, chunk in enumerate(_split_text(md_content, 500, 50)):
        from app.models.document import Chunk
        db.add(Chunk(
            doc_id=document.id,
            content=chunk["content"],
            chunk_index=i,
            start_char=chunk["start"],
            end_char=chunk["end"],
        ))
    return document


async def _run_doc_parse_task(task, batch_id: UUID) -> Dict[str, Any]:
    """异步执行解析批次"""
    async with get_db_context() as db:
        batch = await db.get(DocParseBatch, batch_id)
        if not batch:
            return {"error": f"解析批次 {batch_id} 不存在"}

        batch.status = "running"
        batch.started_at = datetime.utcnow()
        await db.commit()

        try:
            parser_model = await db.get(Model, batch.parser_model_id)
            if not parser_model or parser_model.model_type != "doc_parser":
                raise ValueError(f"解析服务 {batch.parser_model_id} 不存在或类型错误")
            batch.parser_model_name = parser_model.name

            results = (await db.execute(
                select(DocParseResult).where(DocParseResult.batch_id == batch_id)
            )).scalars().all()
            if not results:
                raise ValueError("批次中没有待解析的文件")

            minio = get_minio_service()
            params = dict(batch.config or {})
            provider = parser_model.provider or "mineru"

            # 官方API：整批一次提交；自部署/自定义：逐文件调用
            if provider == "mineru_api":
                files = []
                file_map = {}
                for r in results:
                    try:
                        content = await _load_file(minio, r.object_name)
                    except Exception as e:
                        r.status = "failed"
                        r.error = str(e)
                        continue
                    files.append({"name": r.file_name, "content": content})
                    file_map[r.file_name] = r

                async def on_progress(items: List[Dict[str, Any]]):
                    done = sum(1 for it in items if it.get("state") in ("done", "failed"))
                    batch.progress = int(done / max(len(results), 1) * 90)
                    await db.commit()

                # 官方API批量解析可能超过全局30分钟时限，这里放宽到约2小时
                parsed_list = await parse_batch_mineru_official(
                    files,
                    api_key=parser_model.api_key_encrypted,
                    params=params,
                    timeout=7200.0,
                    on_progress=on_progress,
                )
                for parsed in parsed_list:
                    r = file_map.get(parsed["name"])
                    if not r:
                        # file_name 与 data_id 不一致时按顺序兜底匹配
                        continue
                    if parsed["status"] == "success":
                        r.status = "success"
                        r.md_content = parsed["md_content"]
                        r.content_list = parsed.get("content_list")
                    else:
                        r.status = "failed"
                        r.error = parsed.get("error")
            else:
                for idx, r in enumerate(results):
                    if r.status == "success":
                        continue
                    try:
                        content = await _load_file(minio, r.object_name)
                        r.status = "running"
                        await db.commit()
                        start = time.monotonic()
                        md = await parse_document_with_model(
                            file_content=content,
                            filename=r.file_name,
                            endpoint=parser_model.endpoint or "",
                            provider=provider,
                            api_key=parser_model.api_key_encrypted,
                            params=params,
                        )
                        r.status = "success"
                        r.md_content = md
                        r.duration = round(time.monotonic() - start, 2)
                    except Exception as e:
                        r.status = "failed"
                        r.error = str(e)
                        logger.error(f"解析文件 {r.file_name} 失败: {e}")
                    batch.progress = int((idx + 1) / len(results) * 90)
                    await db.commit()

            # 成功的产物写入 Document+Chunk
            for r in results:
                if r.status == "success" and r.md_content and not r.doc_id:
                    document = await _save_document(db, batch, r.file_name, r.md_content)
                    r.doc_id = document.id

            batch.success_files = sum(1 for r in results if r.status == "success")
            batch.failed_files = sum(1 for r in results if r.status == "failed")
            batch.progress = 100
            batch.completed_at = datetime.utcnow()
            batch.status = "completed" if batch.success_files > 0 else "failed"
            if batch.failed_files and not batch.success_files:
                batch.error = "；".join(
                    f"{r.file_name}: {r.error}" for r in results if r.error
                )[:2000]
            await db.commit()

            return {
                "batch_id": str(batch_id),
                "status": batch.status,
                "total": len(results),
                "success": batch.success_files,
                "failed": batch.failed_files,
            }

        except Exception as e:
            logger.error(f"文档解析批次 {batch_id} 失败: {e}")
            await db.rollback()
            batch = await db.get(DocParseBatch, batch_id)
            if batch:
                batch.status = "failed"
                batch.error = str(e)
                batch.completed_at = datetime.utcnow()
                await db.commit()
            return {"error": str(e)}
