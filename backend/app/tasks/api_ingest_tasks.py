# API 全链路入库任务
#
# 流程：远端建库/选库 -> 上传原始文件 -> 触发并轮询解析 -> 拉取远端分片
#       -> 落本地 Document/Chunk -> 生成或导入 QA -> 可选自动发起调用批次
#
# 成败标准不是"上传接口返回 200"，而是解析完成且拿到分片；RAGFlow/Dify 的
# 上传都是异步的，跳过轮询会把尚未解析的空库当成成功。
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
import logging

from sqlalchemy import delete, func, select

from app.core.celery_app import celery_app
from app.core.database import get_db_context
from app.models.api_ingest import ApiIngestTask
from app.models.dataset import Dataset, QARecord
from app.models.document import Chunk, Document
from app.models.invocation import InvocationBatch
from app.models.model import Model
from app.models.rag_system import RAGSystem
from app.services.api_ingest import create_connector
from app.services.api_ingest.base import ConnectorError, RemoteChunk, RemoteDocument
from app.services.dataset import DatasetGenerator
from app.services.dataset.adapters.existing_doc_adapter import ExistingDocAdapter
from app.services.documents import refresh_dataset_stats
from app.services.llm import create_embeddings_from_config, create_llm_from_config
from app.services.storage.minio_service import get_minio_service
from app.tasks._common import format_error, mark_task_failed, run_async

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="api_ingest_task",
                 soft_time_limit=55 * 60, time_limit=60 * 60)
def api_ingest_task(self, ingest_task_id: str) -> Dict[str, Any]:
    """执行 API 全链路入库"""
    return run_async(_run_ingest(self, UUID(ingest_task_id)))


def _progress(task, ingest: ApiIngestTask, progress: int, stage: str, **extra: Any) -> None:
    ingest.progress = progress
    ingest.stage = stage
    task.update_state(
        state="PROGRESS",
        meta={"progress": progress, "stage": stage, **extra},
    )


async def _run_ingest(task, ingest_task_id: UUID) -> Dict[str, Any]:
    async with get_db_context() as db:
        ingest = await db.get(ApiIngestTask, ingest_task_id)
        if not ingest:
            return {"error": f"入库任务 {ingest_task_id} 不存在"}

        config: Dict[str, Any] = dict(ingest.config or {})
        files_meta: List[Dict[str, Any]] = [dict(item) for item in (ingest.files or [])]

        ingest.status = "running"
        ingest.started_at = datetime.utcnow()
        await db.commit()

        try:
            rag_system = await db.get(RAGSystem, ingest.rag_system_id)
            if not rag_system:
                raise ConnectorError("RAG 系统不存在，可能已被删除")

            connector = create_connector(rag_system.system_type, rag_system.connection_config or {})

            # ---------------------------------------------------------- 知识库
            _progress(task, ingest, 5, "ensuring_knowledge_base")
            kb_id = ingest.remote_kb_id or config.get("kb_id")
            if not kb_id:
                if not connector.capabilities.create_knowledge_base:
                    raise ConnectorError(
                        f"{connector.display_name} 不支持自动建库，请在连接配置里指定已有知识库 ID"
                    )
                kb_name = config.get("new_kb_name") or config.get("dataset_name") or (
                    f"{rag_system.name} eval {datetime.utcnow().strftime('%Y%m%d-%H%M')}"
                )
                kb = await connector.create_knowledge_base(
                    str(kb_name),
                    description=config.get("kb_description"),
                    space_id=config.get("space_id"),
                )
                kb_id = kb.id
                ingest.remote_kb_id = kb_id
                ingest.remote_kb_name = kb.name
            else:
                ingest.remote_kb_id = kb_id
                ingest.remote_kb_name = config.get("kb_name") or ingest.remote_kb_name
            await db.commit()

            # ---------------------------------------------------------- 会话
            if connector.capabilities.create_chat:
                chat_name = config.get("chat_name") or f"jq-eval-{ingest.id}"
                ingest.remote_chat_id = await connector.ensure_chat(chat_name, [kb_id])
                await db.commit()

            # ---------------------------------------------------------- 数据集
            dataset: Optional[Dataset] = None
            if ingest.dataset_id:
                dataset = await db.get(Dataset, ingest.dataset_id)
            if not dataset:
                dataset = Dataset(
                    name=config.get("dataset_name") or (
                        f"{rag_system.name} API 入库 {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
                    ),
                    description=f"通过 {connector.display_name} API 入库并生成",
                    source_type="api_ingest",
                    source_url=f"{connector.display_name}:{kb_id}",
                    status="importing",
                    dataset_metadata={
                        "rag_system_id": str(rag_system.id),
                        "rag_system_type": rag_system.system_type,
                        "remote_kb_id": kb_id,
                        "remote_chat_id": ingest.remote_chat_id,
                    },
                )
                db.add(dataset)
                await db.flush()
                ingest.dataset_id = dataset.id
            else:
                dataset.status = "importing"
            await db.commit()

            # ---------------------------------------------------------- 上传
            minio = get_minio_service()
            uploaded: List[RemoteDocument] = []
            for index, meta in enumerate(files_meta):
                _progress(
                    task, ingest,
                    10 + int(35 * index / max(len(files_meta), 1)),
                    "uploading",
                    current=index,
                    total=len(files_meta),
                )
                object_name = meta.get("object_name")
                if not object_name:
                    meta["status"] = "failed"
                    meta["error"] = "缺少 MinIO 对象名"
                    continue
                download = await minio.download_file(bucket="documents", object_name=object_name)
                if not download.get("success"):
                    meta["status"] = "failed"
                    meta["error"] = f"读取原始文件失败：{download.get('error')}"
                    continue
                try:
                    remote_doc = await connector.upload_document(
                        kb_id,
                        meta["name"],
                        download["data"],
                        meta.get("content_type"),
                    )
                    meta["remote_doc_id"] = remote_doc.id
                    meta["status"] = "uploaded"
                    uploaded.append(remote_doc)
                except Exception as exc:
                    meta["status"] = "failed"
                    meta["error"] = format_error(exc)
                ingest.files = list(files_meta)
                ingest.processed_files = index + 1
                await db.commit()

            failed_uploads = [m for m in files_meta if m.get("status") == "failed"]
            if not uploaded:
                raise ConnectorError(
                    "所有文件上传失败：" + "; ".join(
                        f"{m.get('name')}: {m.get('error')}" for m in failed_uploads[:3]
                    )
                )

            # ---------------------------------------------------------- 解析
            document_ids = [doc.id for doc in uploaded]
            if connector.capabilities.parse_documents:
                _progress(task, ingest, 50, "triggering_parse")
                await connector.trigger_parse(kb_id, document_ids)
            await db.commit()

            _progress(task, ingest, 55, "parsing")
            remote_docs = await connector.wait_documents_ready(
                kb_id,
                document_ids,
                timeout=float(config.get("parse_timeout") or 1800.0),
                interval=float(config.get("poll_interval") or 3.0),
            )
            doc_status = {doc.id: doc for doc in remote_docs}
            for meta in files_meta:
                remote_id = meta.get("remote_doc_id")
                if remote_id and remote_id in doc_status:
                    meta["status"] = doc_status[remote_id].status
                    if doc_status[remote_id].error:
                        meta["error"] = doc_status[remote_id].error
            ingest.files = list(files_meta)
            failed_docs = [doc for doc in remote_docs if doc.failed]
            if len(failed_docs) == len(remote_docs):
                raise ConnectorError(
                    "远端文档解析全部失败：" + "; ".join(
                        f"{doc.name}: {doc.error or 'unknown'}" for doc in failed_docs[:3]
                    )
                )
            await db.commit()

            # ---------------------------------------------------------- 分片
            _progress(task, ingest, 70, "fetching_chunks")
            local_docs: List[Document] = []
            all_chunks: List[Chunk] = []
            if connector.capabilities.list_chunks:
                for meta in files_meta:
                    remote_id = meta.get("remote_doc_id")
                    if not remote_id or meta.get("status") == "failed":
                        continue
                    try:
                        chunks = await connector.list_chunks(kb_id, remote_id)
                    except ConnectorError as exc:
                        logger.warning(f"拉取 {meta.get('name')} 分片失败: {exc}")
                        chunks = []
                    document, db_chunks = await _save_remote_document(
                        db,
                        dataset_id=dataset.id,
                        system_type=rag_system.system_type,
                        kb_id=kb_id,
                        file_meta=meta,
                        chunks=chunks,
                    )
                    local_docs.append(document)
                    all_chunks.extend(db_chunks)
                    meta["local_document_id"] = str(document.id)
                    meta["chunk_count"] = len(db_chunks)
                ingest.files = list(files_meta)
                await db.commit()

            # ---------------------------------------------------------- QA
            _progress(task, ingest, 82, "building_questions")
            qa_count = await _build_qa(
                task,
                db,
                ingest,
                dataset,
                config,
                local_docs,
                all_chunks,
            )

            await refresh_dataset_stats(
                db,
                dataset.id,
                mark_ground_truth=await _has_ground_truth(db, dataset.id),
                mark_contexts=await _has_contexts(db, dataset.id),
            )
            dataset.status = "ready"

            # ---------------------------------------------------------- 可选：自动调用
            if config.get("auto_invoke"):
                _progress(task, ingest, 95, "dispatching_invocation")
                try:
                    from app.tasks.invocation_tasks import invocation_task

                    batch = InvocationBatch(
                        name=config.get("invocation_name")
                        or f"{dataset.name} - {rag_system.name} 调用",
                        dataset_id=dataset.id,
                        rag_system_id=rag_system.id,
                        total_count=qa_count,
                        status="pending",
                    )
                    db.add(batch)
                    await db.flush()
                    batch_id = str(batch.id)
                    await db.commit()
                    invocation_task.delay(batch_id)
                    config = {**config, "invocation_batch_id": batch_id}
                    ingest.config = config
                except Exception as exc:
                    # 入库已完成，自动调用失败不应把整个任务标失败
                    logger.error(f"自动发起调用批次失败: {exc}")
                    config = {**config, "invocation_dispatch_error": format_error(exc)}
                    ingest.config = config

            ingest.status = "completed"
            ingest.stage = "completed"
            ingest.progress = 100
            ingest.completed_at = datetime.utcnow()
            ingest.error = (
                f"{len(failed_uploads)} 个文件上传失败" if failed_uploads else None
            )
            await db.commit()

            return {
                "ingest_task_id": str(ingest.id),
                "dataset_id": str(dataset.id),
                "remote_kb_id": kb_id,
                "documents": len(local_docs),
                "chunks": len(all_chunks),
                "questions": qa_count,
                "failed_files": len(failed_uploads),
            }

        except Exception as exc:
            logger.error(f"API 入库失败: {exc}")
            await mark_task_failed(db, ApiIngestTask, ingest_task_id, format_error(exc), logger)
            return {"error": format_error(exc), "ingest_task_id": str(ingest_task_id)}


async def _save_remote_document(
    db,
    *,
    dataset_id: UUID,
    system_type: str,
    kb_id: str,
    file_meta: Dict[str, Any],
    chunks: List[RemoteChunk],
) -> tuple:
    """把远端文档及其分片落本地；同一远端文档重跑时先删旧记录，避免重复"""
    marker = f"api_ingest://{system_type}/{kb_id}/{file_meta.get('remote_doc_id')}"
    existing = await db.execute(
        select(Document).where(
            Document.dataset_id == dataset_id,
            Document.file_path == marker,
        )
    )
    for old in existing.scalars().all():
        # 显式删分片：SQLite 测试库默认不启用外键级联，只靠 ondelete 会留孤儿
        await db.execute(delete(Chunk).where(Chunk.doc_id == old.id))
        await db.delete(old)

    name = file_meta.get("name") or "document"
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    document = Document(
        title=name,
        content="\n\n".join(chunk.content for chunk in chunks) if chunks else "",
        file_path=marker,
        file_type=extension or None,
        source_type="api_ingest",
        source_url=marker,
        dataset_id=dataset_id,
        doc_metadata={
            "remote_system": system_type,
            "remote_kb_id": kb_id,
            "remote_document_id": file_meta.get("remote_doc_id"),
            "remote_document_name": name,
            "minio_object": file_meta.get("object_name"),
        },
    )
    db.add(document)
    await db.flush()

    db_chunks: List[Chunk] = []
    for index, chunk in enumerate(chunks):
        record = Chunk(
            doc_id=document.id,
            content=chunk.content,
            chunk_index=index,
            chunk_metadata={
                "remote_chunk_id": chunk.id,
                "remote_document_id": chunk.document_id or file_meta.get("remote_doc_id"),
                "remote_kb_id": kb_id,
                "remote_system": system_type,
                "remote_index": chunk.index,
            },
        )
        db.add(record)
        db_chunks.append(record)
    await db.flush()
    return document, db_chunks


async def _has_ground_truth(db, dataset_id: UUID) -> bool:
    count = await db.scalar(
        select(func.count(QARecord.id)).where(
            QARecord.dataset_id == dataset_id,
            QARecord.ground_truth.isnot(None),
            QARecord.ground_truth != "",
        )
    )
    return bool(count)


async def _has_contexts(db, dataset_id: UUID) -> bool:
    result = await db.execute(
        select(QARecord.snapshot).where(QARecord.dataset_id == dataset_id).limit(200)
    )
    for snapshot in result.scalars().all():
        if isinstance(snapshot, dict) and snapshot.get("contexts"):
            return True
    return False


def _match_chunk_ids(contexts: List[str], chunks: List[Chunk]) -> List[UUID]:
    """把 QA 的 context 文本对回本地分片，填充 target_chunk_ids

    先精确相等，再双向包含。Ragas 生成的 context 基本就是分片原文，
    但有的系统会做空白/前后缀裁剪，所以不能只靠 ==。
    """
    matched: List[UUID] = []
    for context in contexts or []:
        text = (context or "").strip()
        if not text:
            continue
        exact = [chunk.id for chunk in chunks if chunk.content.strip() == text]
        if exact:
            matched.extend(exact)
            continue
        partial = [
            chunk.id
            for chunk in chunks
            if text in chunk.content or (len(chunk.content) > 80 and chunk.content in text)
        ]
        matched.extend(partial[:3])
    # 去重且保持顺序
    seen = set()
    result: List[UUID] = []
    for chunk_id in matched:
        if chunk_id not in seen:
            seen.add(chunk_id)
            result.append(chunk_id)
    return result


async def _build_qa(
    task,
    db,
    ingest: ApiIngestTask,
    dataset: Dataset,
    config: Dict[str, Any],
    local_docs: List[Document],
    chunks: List[Chunk],
) -> int:
    """导入问答或基于远端分片生成问答"""
    questions = config.get("questions") or []
    if questions:
        for item in questions:
            question = (item.get("question") or "").strip()
            if not question:
                continue
            contexts = item.get("contexts") or []
            if isinstance(contexts, str):
                contexts = [contexts]
            qa = QARecord(
                dataset_id=dataset.id,
                question=question,
                ground_truth=item.get("ground_truth") or item.get("answer"),
                question_type=item.get("question_type") or "simple",
                difficulty=item.get("difficulty"),
                snapshot={
                    "contexts": contexts,
                    "source": "api_ingest_import",
                    "remote_kb_id": ingest.remote_kb_id,
                },
                qa_metadata={
                    "source": "api_ingest",
                    "rag_system_type": config.get("rag_system_type"),
                },
                target_chunk_ids=_match_chunk_ids(contexts, chunks),
            )
            db.add(qa)
        return len(questions)

    if not config.get("auto_generate"):
        return 0
    if not chunks:
        logger.warning("没有远端分片，跳过 QA 生成（该系统的分片接口可能未开放）")
        return 0

    llm_model_id = config.get("llm_model_id")
    embedding_model_id = config.get("embedding_model_id")
    if not llm_model_id or not embedding_model_id:
        raise ConnectorError(
            "自动生成问答需要 llm_model_id 与 embedding_model_id；"
            "也可以改传 questions 列表直接导入，或关闭 auto_generate 只做文档入库。"
        )

    llm_model = await db.get(Model, UUID(str(llm_model_id)))
    embedding_model = await db.get(Model, UUID(str(embedding_model_id)))
    if not llm_model:
        raise ConnectorError(f"LLM 模型 {llm_model_id} 不存在")
    if not embedding_model:
        raise ConnectorError(f"Embedding 模型 {embedding_model_id} 不存在")

    llm = await create_llm_from_config(llm_model)
    embeddings = await create_embeddings_from_config(embedding_model)
    generator = DatasetGenerator(llm, embeddings)

    document_ids = [doc.id for doc in local_docs]
    if not document_ids:
        raise ConnectorError("没有可用的本地文档，无法生成问答")
    adapter = ExistingDocAdapter(document_ids=document_ids, db=db)

    top_k = int(config.get("test_size") or 10)
    qa_records = await generator.generate(
        adapter=adapter,
        test_size=top_k,
        distributions=config.get("distributions"),
    )

    for item in qa_records:
        contexts = item.get("contexts") or []
        db.add(
            QARecord(
                dataset_id=dataset.id,
                question=item.get("question") or "",
                ground_truth=item.get("ground_truth"),
                question_type=item.get("evolution_type") or "simple",
                snapshot={
                    "contexts": contexts,
                    "evolution_type": item.get("evolution_type"),
                    "source": "api_ingest_generated",
                    "remote_kb_id": ingest.remote_kb_id,
                    "generated_at": datetime.utcnow().isoformat(),
                },
                qa_metadata=item.get("metadata") or {"source": "api_ingest"},
                target_chunk_ids=_match_chunk_ids(contexts, chunks),
            )
        )

    return len(qa_records)
