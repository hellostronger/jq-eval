# RAG系统调用相关异步任务
from typing import Dict, List, Any
from datetime import datetime
import asyncio
import logging
import time
from uuid import UUID

from app.core.celery_app import celery_app
from app.core.exceptions import TaskCancelled
from app.tasks._common import run_async, format_error
from app.tasks.persistence import commit_with_retry
from app.core.database import get_db_context
from app.models.invocation import InvocationBatch, InvocationResult
from app.models.dataset import Dataset, QARecord
from app.models.rag_system import RAGSystem
from app.models.model import Model
from app.services.adapters import AdapterFactory
from app.services.diagnostics.trace import compact_trace
from app.services.dataset.qa_scope import apply_scope, count_in_scope
from sqlalchemy import select

logger = logging.getLogger(__name__)


async def _raise_if_cancelled(db, batch_id: UUID) -> None:
    """逐条 QA 边界重读取消标志。

    用独立短查询而不是复用外层 session 里的 batch 对象：长任务里该对象可能
    已被过期快照，读不到其它连接写入的 flag。
    """
    flag = await db.execute(
        select(InvocationBatch.cancel_requested).where(InvocationBatch.id == batch_id)
    )
    if flag.scalar():
        raise TaskCancelled()


def _write(batch_counters=None, **fields):
    """构造"落一条调用结果"的写回调：可选先删旧行、再插新行、同事务更新批次计数。"""
    from sqlalchemy import delete

    delete_result_id = fields.pop("delete_result_id", None)
    dedupe_qa_record_id = fields.pop("dedupe_qa_record_id", None)

    async def apply(db):
        if delete_result_id:
            await db.execute(
                delete(InvocationResult).where(InvocationResult.id == delete_result_id)
            )
        if dedupe_qa_record_id is not None:
            # 一个批次里同一条 QA 只应有一行结果。worker 被 SIGKILL 后 Celery 会把
            # invocation_task 重投，旧实现每次重投都追加一行：实测 5 题的批次长出 6 行，
            # completed_count 由终态反推变成 6/5（进度超 100%），下游评估还把这道题
            # 双计一次，均值被拉偏。重投时先删掉同题旧行再写新行。
            await db.execute(
                delete(InvocationResult).where(
                    InvocationResult.batch_id == fields["batch_id"],
                    InvocationResult.qa_record_id == dedupe_qa_record_id,
                )
            )
        db.add(InvocationResult(**fields))
        if batch_counters is not None:
            batch = await db.get(InvocationBatch, fields["batch_id"])
            if batch:
                batch.completed_count, batch.failed_count = batch_counters
    return apply


async def _commit_with_retry(apply, batch_id: UUID = None, attempts: int = 3) -> None:
    """写一条调用结果；连接断了就换新 session 重做。

    一次 RAG 调用要两三分钟，而远端 PG 随时可能掐线（实际反复踩到
    asyncpg ConnectionDoesNotExistError）。用调用方那条长 session 提交，
    断了就是整条回滚——几分钟的 Token 白花。换新 session 重试一次通常就过去了。

    get_db_context 在调用时按本模块命名空间解析，测试可以就地替换。
    """
    await commit_with_retry(
        apply,
        get_session=get_db_context,
        label="写入调用结果",
        context=f"batch_id={batch_id}",
        attempts=attempts,
    )


async def _reconcile_terminal_state(batch_id: UUID, error: str = None, attempts: int = 3) -> str:
    """按结果表重算批次终态；连接抖动时换新 session 重试。

    远端 PG/Redis 掉线偏偏容易落在"跑完最后一条、写终态"这一步：每条 InvocationResult
    都已逐条 commit（一次调用几分钟的真实成本），却因为一条 UPDATE 失败被标成 failed，
    下游评估又以"批次必须 completed"为前置条件，整批成果白白作废。
    所以终态不靠内存里的计数，而是回查结果表：全部样本都有结果就按 completed 落，
    原始异常只作为 error 记录，不推翻已经真实完成的工作。
    """
    async def apply(db):
        batch = await db.get(InvocationBatch, batch_id)
        if not batch:
            return "missing"

        counts = await db.execute(
            select(InvocationResult.qa_record_id, InvocationResult.status)
            .where(InvocationResult.batch_id == batch_id)
            .order_by(InvocationResult.created_at, InvocationResult.id)
        )
        # 按"每条 QA 的最后一行"统计，而不是按行数：重投留下的重复行会把
        # completed_count 顶到 total_count 以上（实测 6/5），进度条超 100%，
        # 终态判定也跟着失真。取最后一行＝以最新一次调用为准。
        last_status_by_qa: dict = {}
        for qa_id, status in counts.all():
            last_status_by_qa[qa_id] = status
        done = len(last_status_by_qa)
        by_status = {
            "success": sum(1 for s in last_status_by_qa.values() if s == "success"),
            "failed": sum(1 for s in last_status_by_qa.values() if s != "success"),
        }
        # total_count 缺失时回退到"批次取样范围内的条数"，不是整个数据集：
        # 只跑 40 题的批次按 2556 题判未完成，会永远落在 failed 且重试补不完
        expected = batch.total_count or await count_in_scope(db, batch) or 0
        batch.completed_count = by_status["success"]
        batch.failed_count = by_status["failed"]

        if batch.cancel_requested:
            batch.status = "cancelled"
            batch.error = error or "批次已被用户取消"
            batch.cancel_requested = False
        elif expected and done >= expected:
            # 全部样本都有结果：跑完了就是跑完了，哪怕收尾时连接断了
            batch.status = "completed"
            batch.error = error
        else:
            batch.status = "failed"
            batch.error = error or f"批次未完成（{done}/{expected}）"
        batch.completed_at = datetime.utcnow()
        return batch.status

    try:
        return await commit_with_retry(
            apply,
            get_session=get_db_context,
            label="写入批次终态",
            context=f"batch_id={batch_id}",
            attempts=attempts,
        )
    except Exception as exc:
        logger.error(f"批次终态始终写不进去 batch_id={batch_id}: {exc}")
        return "unknown"


async def _run_invocation_guarded(task, batch_id: UUID) -> Dict[str, Any]:
    """_run_invocation 的最外层兜底：任何逃逸异常都必须把批次落成明确终态。

    批次刚建好就炸（schema 未迁移、模型类字段与库不一致等）时，函数内部那个
    except 根本还没进入，状态会永远停在 running、error 为空：界面显示"执行中"，
    重试又被 batch_in_flight 挡死，只能人工改库。实际踩过（worker 比 API 先起，
    读到还没有 cancel_requested 列的旧库直接 UndefinedColumnError）。
    """
    try:
        return await _run_invocation(task, batch_id)
    except TaskCancelled:
        raise
    except Exception as e:
        await _reconcile_terminal_state(batch_id, format_error(e))
        raise


async def _run_retry_guarded(task, batch_id: UUID, result_ids: List[UUID]) -> Dict[str, Any]:
    """同上：重试任务炸在头部也要把批次落成明确终态，不能留在 running"""
    try:
        return await _run_retry(task, batch_id, result_ids)
    except TaskCancelled:
        raise
    except Exception as e:
        await _reconcile_terminal_state(batch_id, format_error(e))
        raise


async def _prepare_direct_llm_config(connection_config: Dict[str, Any], db) -> Dict[str, Any]:
    """为直连LLM类型准备完整配置"""
    llm_model_id = connection_config.get("llm_model_id")
    if not llm_model_id:
        return connection_config

    try:
        result = await db.execute(select(Model).where(Model.id == UUID(llm_model_id)))
        model = result.scalar_one_or_none()
        if not model:
            return connection_config

        config = connection_config.copy()
        config["api_endpoint"] = model.endpoint
        config["api_key"] = model.api_key_encrypted or ""
        config["model_name"] = model.model_name or model.name
        config["provider"] = connection_config.get("provider") or model.provider or "openai"

        if model.params:
            config["temperature"] = connection_config.get("temperature") or model.params.get("temperature", 0.7)
            config["max_tokens"] = connection_config.get("max_tokens") or model.params.get("max_tokens", 2048)
            # 额外请求参数：调用方配置可覆盖模型默认
            extra = dict(model.params.get("extra_params") or {})
            extra.update(connection_config.get("extra_params") or {})
            if extra:
                config["extra_params"] = extra

        return config
    except Exception as e:
        logger.error(f"获取LLM模型配置失败: {e}")
        return connection_config


@celery_app.task(bind=True, name="invocation_task",
                 soft_time_limit=110 * 60, time_limit=115 * 60)
def invocation_task(self, batch_id: str) -> Dict[str, Any]:
    """执行RAG系统调用批次

    Args:
        batch_id: 调用批次ID (UUID字符串格式)
    """
    return run_async(_run_invocation_guarded(self, UUID(batch_id)))


@celery_app.task(bind=True, name="retry_invocation_task")
def retry_invocation_task(self, batch_id: str, result_ids: List[str]) -> Dict[str, Any]:
    """重试调用批次中指定的结果

    Args:
        batch_id: 调用批次ID
        result_ids: 要重试的结果ID列表
    """
    return run_async(_run_retry_guarded(self, UUID(batch_id), [UUID(rid) for rid in result_ids]))


async def _run_retry(task, batch_id: UUID, result_ids: List[UUID]) -> Dict[str, Any]:
    """异步执行重试"""
    async with get_db_context() as db:
        batch = await db.get(InvocationBatch, batch_id)
        if not batch:
            return {"error": f"调用批次 {batch_id} 不存在"}

        rag_system = await db.get(RAGSystem, batch.rag_system_id)
        if not rag_system:
            return {"error": f"RAG系统 {batch.rag_system_id} 不存在"}

        # 获取要重试的结果
        from sqlalchemy import select
        results = await db.execute(
            select(InvocationResult).where(InvocationResult.id.in_(result_ids))
        )
        retry_results = results.scalars().all()

        if not retry_results:
            return {"error": "没有找到要重试的结果"}

        # 创建RAG适配器
        config = rag_system.connection_config
        if rag_system.system_type == "direct_llm":
            config = await _prepare_direct_llm_config(config, db)
        adapter = AdapterFactory.create(
            rag_system.system_type,
            config
        )

        batch.status = "running"
        batch.error = None  # 重试成功后不应继续展示上一次的失败原因
        await db.commit()

        # 批量预取要重试的问题，避免循环内逐条 db.get
        qa_ids = {r.qa_record_id for r in retry_results}
        qa_result = await db.execute(select(QARecord).where(QARecord.id.in_(qa_ids)))
        qa_map = {qa.id: qa for qa in qa_result.scalars().all()}

        success_count = 0
        fail_count = 0

        try:
            for inv_result in retry_results:
                await _raise_if_cancelled(db, batch_id)
                old_id = inv_result.id
                qa_record = qa_map.get(inv_result.qa_record_id)
                old_question = inv_result.question
                # 同主流程：别把只读事务挂过整次 RAG 调用
                await db.commit()

                try:
                    if not qa_record:
                        # 问题记录已不存在：补一条写明原因的失败记录，
                        # 保证"每条 QA 都有结果"，否则 total 永远凑不满
                        await _commit_with_retry(_write(
                            batch_id=batch_id,
                            qa_record_id=inv_result.qa_record_id,
                            rag_system_id=rag_system.id,
                            question=old_question,
                            status="failed",
                            error="问题记录已不存在，无法重试",
                            delete_result_id=old_id,
                        ))
                        fail_count += 1
                        continue

                    # 先调用、后写库。旧写法是 delete + flush 开一个事务，然后在
                    # 事务里 await adapter.query()：一次调用两三分钟，远端 PG 把这根
                    # idle-in-transaction 的连接掐了，commit 时报 ConnectionDoesNotExist，
                    # 删除和新增一起回滚——几分钟的真实调用成果原地丢失。
                    start_time = time.time()
                    response = await adapter.query(qa_record.question)
                    latency = time.time() - start_time

                    # 从 RAGResponse 对象获取数据
                    answer = response.answer or ""
                    contexts = response.contexts or []
                    retrieval_ids = response.retrieval_ids or []

                    await _commit_with_retry(_write(
                        batch_id=batch_id,
                        qa_record_id=qa_record.id,
                        rag_system_id=rag_system.id,
                        question=qa_record.question,
                        answer=answer,
                        contexts=contexts,
                        retrieval_ids=retrieval_ids,
                        trace=compact_trace(getattr(response, "trace", None)),
                        latency=latency,
                        # 尊重 adapter 的 success 标志（同主流程）
                        status="success" if response.success else "failed",
                        error=None if response.success else (response.error or "RAG 调用失败"),
                        delete_result_id=old_id,
                    ))
                    if response.success:
                        success_count += 1
                    else:
                        fail_count += 1

                except Exception as e:
                    logger.error(f"重试调用 {inv_result.id} 失败: {e}")
                    # 失败也要留痕：删旧行 + 写失败行，一次短事务
                    await _commit_with_retry(_write(
                        batch_id=batch_id,
                        qa_record_id=inv_result.qa_record_id,
                        rag_system_id=rag_system.id,
                        question=old_question,
                        status="failed",
                        error=format_error(e),
                        delete_result_id=old_id,
                    ), batch_id)
                    fail_count += 1

            # 计数不再做增量加减（重试成功项会造成重复计数），直接按结果表重算
            await _reconcile_terminal_state(batch_id)

            return {
                "batch_id": str(batch_id),
                "retried": len(retry_results),
                "success": success_count,
                "failed": fail_count
            }

        except TaskCancelled:
            logger.info(f"重试任务 batch_id={batch_id} 已被用户取消")
            await db.rollback()
            batch = await db.get(InvocationBatch, batch_id)
            if batch:
                batch.status = "cancelled"
                batch.error = "批次已被用户取消"
                batch.cancel_requested = False
                await db.commit()
            return {"batch_id": str(batch_id), "status": "cancelled"}

        except Exception as e:
            # 与 _run_invocation 对齐：任何未预期异常都必须把批次落成明确终态，
            # 否则批次永久停留在 running
            logger.error(f"重试任务异常 batch_id={batch_id}: {e}")
            await db.rollback()
            await _reconcile_terminal_state(batch_id, format_error(e))
            raise


async def _run_invocation(task, batch_id: UUID) -> Dict[str, Any]:
    """异步执行RAG调用"""
    async with get_db_context() as db:
        # 获取调用批次
        batch = await db.get(InvocationBatch, batch_id)
        if not batch:
            return {"error": f"调用批次 {batch_id} 不存在"}

        # 重投保护：Redis broker 抖动后 kombu 会把"已投递未 ack"的消息重新入队，
        # 实测同一批次/评估被再跑一遍（一次评估白花 5 分钟且撞上配额上限）。
        # 已完成/已取消都是终态：取消是用户明确的决定，重投不该把它翻回 running。
        # 手工重跑走 POST /invocations/{id}/run，那里会先把状态置回 running 再派发。
        if batch.status in ("completed", "cancelled"):
            logger.warning(
                f"调用批次 {batch_id} 已处于终态 {batch.status}，忽略重复投递（不重新调用 RAG）"
            )
            return {"batch_id": str(batch_id), "status": f"already_{batch.status}"}

        # 更新状态
        batch.status = "running"
        batch.error = None  # 重新运行要清掉上一次失败的错误信息，否则界面一直显示旧原因
        batch.started_at = datetime.utcnow()
        await db.commit()

        try:
            # 获取数据集
            dataset = await db.get(Dataset, batch.dataset_id)
            if not dataset:
                raise ValueError(f"数据集 {batch.dataset_id} 不存在")

            # 获取RAG系统
            rag_system = await db.get(RAGSystem, batch.rag_system_id)
            if not rag_system:
                raise ValueError(f"RAG系统 {batch.rag_system_id} 不存在")

            # 获取QA记录。用 ORM 查询而非 text() 裸 SQL：text() 不走类型
            # 转换，PostgreSQL 能隐式接受 UUID 字符串，SQLite 却不认，
            # 会直接抛 "Error binding parameter 0 - probably unsupported type"。
            # 取样范围（qa_limit/qa_offset）决定这次真跑多少条
            qa_result = await db.execute(
                apply_scope(
                    select(QARecord.id, QARecord.question)
                    .where(QARecord.dataset_id == dataset.id)
                    .order_by(QARecord.created_at),
                    batch,
                )
            )
            qa_list = [{"id": r.id, "question": r.question} for r in qa_result.all()]
            batch.total_count = len(qa_list)
            await db.commit()

            # 创建RAG适配器
            config = rag_system.connection_config
            if rag_system.system_type == "direct_llm":
                config = await _prepare_direct_llm_config(config, db)
            adapter = AdapterFactory.create(
                rag_system.system_type,
                config
            )

            # 执行调用
            completed = 0
            failed = 0
            for qa in qa_list:
                await _raise_if_cancelled(db, batch_id)
                # 关掉刚才那次只读查询开启的事务：长调用期间挂着 idle-in-transaction
                # 的连接会被远端 PG/代理掐断，commit 时才炸，整条结果原地丢失
                await db.commit()
                try:
                    start_time = time.time()
                    # 调用RAG系统
                    response = await adapter.query(qa["question"])
                    latency = time.time() - start_time

                    # 从 RAGResponse 对象获取数据
                    answer = response.answer or ""
                    contexts = response.contexts or []
                    retrieval_ids = response.retrieval_ids or []

                    if response.success:
                        completed += 1
                    else:
                        failed += 1

                    # 存储结果。adapter 已用 success=False 表达"调用失败"
                    # （如空答案/超限截断）；此处必须尊重该标志，否则失败会被
                    # 记成 success，污染评估输入并让批次统计虚高。
                    await _commit_with_retry(_write(
                        batch_counters=(completed, failed),
                        dedupe_qa_record_id=qa["id"],
                        batch_id=batch_id,
                        qa_record_id=qa["id"],
                        rag_system_id=rag_system.id,
                        question=qa["question"],
                        answer=answer,
                        contexts=contexts,
                        retrieval_ids=retrieval_ids,
                        trace=compact_trace(getattr(response, "trace", None)),
                        latency=latency,
                        status="success" if response.success else "failed",
                        error=None if response.success else (response.error or "RAG 调用失败"),
                    ), batch_id)

                except Exception as e:
                    logger.error(f"调用 QA {qa['id']} 失败: {e}")
                    failed += 1
                    # 失败也要留痕，否则每条 QA 凑不满 total
                    await _commit_with_retry(_write(
                        batch_counters=(completed, failed),
                        dedupe_qa_record_id=qa["id"],
                        batch_id=batch_id,
                        qa_record_id=qa["id"],
                        rag_system_id=rag_system.id,
                        question=qa["question"],
                        status="failed",
                        error=format_error(e),
                    ), batch_id)

                # 更新进度
                progress = (completed + failed) / len(qa_list) * 100
                task.update_state(
                    state="PROGRESS",
                    meta={"progress": progress, "completed": completed, "failed": failed, "total": len(qa_list)}
                )

            # 完成批次：终态回查结果表，收尾连接抖动不会把已完成的调用判成失败
            status = await _reconcile_terminal_state(batch_id)

            return {
                "batch_id": str(batch_id),
                "status": status,
                "total": len(qa_list),
                "completed": completed,
                "failed": failed
            }

        except TaskCancelled:
            # 协作式取消：已完成的每条结果都已逐条 commit，保留不删（调用一次
            # 就是几分钟真实开销），只把批次标成 cancelled 并清掉标志。
            logger.info(f"调用批次 {batch_id} 已被用户取消")
            await db.rollback()
            batch = await db.get(InvocationBatch, batch_id)
            if batch:
                batch.status = "cancelled"
                batch.error = "批次已被用户取消"
                batch.cancel_requested = False
                batch.completed_at = datetime.utcnow()
                await db.commit()
            return {"batch_id": str(batch_id), "status": "cancelled"}

        except Exception as e:
            logger.error(f"调用批次 {batch_id} 失败: {e}")
            await db.rollback()
            # 终态由结果表反推：中途抛错、没跑完才落 failed；
            # 全部跑完只是收尾时连接断了的情况落 completed，不把真实成果判死
            status = await _reconcile_terminal_state(batch_id, format_error(e))
            return {"error": format_error(e), "status": status}