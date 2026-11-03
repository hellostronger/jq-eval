# 评估相关异步任务
import os
from typing import Dict, List, Any
from datetime import datetime
import logging
from sqlalchemy import text, select, delete, func
from uuid import UUID

from app.core.celery_app import celery_app
from app.core.exceptions import TaskCancelled
from app.tasks._common import run_async, make_progress_callback, format_error
from app.tasks.persistence import commit_with_retry
from app.core.database import get_db_context
from app.models.evaluation import Evaluation, EvaluationStatus, EvalResult
from app.models.dataset import Dataset, QARecord
from app.models.model import Model
from app.models.invocation import InvocationResult
from app.services.metrics import MetricEngine, get_metric_engine, METRIC_REGISTRY
from app.services.metrics.context_budget import apply_context_budget

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="evaluation_task",
                 soft_time_limit=110 * 60, time_limit=115 * 60)
def evaluation_task(self, evaluation_id: str) -> Dict[str, Any]:
    """执行单个评估任务

    Args:
        evaluation_id: 评估任务ID (UUID字符串格式)
    """
    return run_async(_run_evaluation(self, UUID(evaluation_id)))


async def _run_evaluation(task, evaluation_id: UUID) -> Dict[str, Any]:
    """异步执行评估"""
    async with get_db_context() as db:
        # 获取评估配置
        evaluation = await db.get(Evaluation, evaluation_id)
        if not evaluation:
            return {"error": f"评估任务 {evaluation_id} 不存在"}

        # acks_late 重投幂等：若结果 commit 成功但 worker 在 ack 前被杀，消息会重投递。
        # 无此保护将全量重打 LLM（浪费 token）并二次插入结果（数据翻倍）
        if evaluation.status == EvaluationStatus.COMPLETED:
            logger.warning(f"评估 {evaluation_id} 已完成但收到重复投递，跳过（acks_late 重投保护）")
            return {"evaluation_id": evaluation_id, "status": "already_completed",
                    "summary": evaluation.summary}

        # 更新状态
        evaluation.status = EvaluationStatus.RUNNING
        evaluation.started_at = datetime.utcnow()
        await db.commit()

        # 本次要评的样本数。异常分支也要拿得到，所以先在 try 外初始化
        expected_count = 0

        try:
            # 获取数据集和QA记录
            dataset = await db.get(Dataset, evaluation.dataset_id)
            if not dataset:
                raise ValueError(f"数据集 {evaluation.dataset_id} 不存在")

            # 获取QA记录。用 ORM 查询而非 text() 裸 SQL：text() 不做类型转换，
            # PostgreSQL 能隐式接受 UUID，SQLite 会抛
            # "Error binding parameter 0 - probably unsupported type"。
            qa_result = await db.execute(
                select(
                    QARecord.id,
                    QARecord.question,
                    QARecord.answer,
                    QARecord.ground_truth,
                    QARecord.target_chunk_ids,
                    QARecord.snapshot,
                )
                .where(QARecord.dataset_id == dataset.id)
                .order_by(QARecord.created_at)
            )
            qa_list = [dict(r._mapping) for r in qa_result.all()]

            # 获取调用结果（如果指定了 invocation_batch_id）
            invocation_results_map = {}
            if evaluation.invocation_batch_id:
                invocation_results = await db.execute(
                    select(InvocationResult)
                    .where(InvocationResult.batch_id == evaluation.invocation_batch_id)
                )
                for ir in invocation_results.scalars().all():
                    invocation_results_map[str(ir.qa_record_id)] = ir

            # 获取模型配置
            logger.info(f"评估任务模型配置: llm_model_id={evaluation.llm_model_id}, embedding_model_id={evaluation.embedding_model_id}")

            llm_config = await db.get(Model, evaluation.llm_model_id) if evaluation.llm_model_id else None
            embedding_config = await db.get(Model, evaluation.embedding_model_id) if evaluation.embedding_model_id else None

            logger.info(f"获取到的模型配置: llm_config={llm_config}, embedding_config={embedding_config}")

            # 设置环境变量供ragas内部创建LLM/Embedding使用
            if llm_config:
                if llm_config.api_key_encrypted:
                    os.environ["OPENAI_API_KEY"] = llm_config.api_key_encrypted
                if llm_config.endpoint:
                    os.environ["OPENAI_API_BASE"] = llm_config.endpoint
                logger.info(f"设置环境变量: OPENAI_API_KEY={'已设置' if llm_config.api_key_encrypted else '未设置'}, OPENAI_API_BASE={llm_config.endpoint}")

            # 初始化模型
            llm = await _init_model(llm_config) if llm_config else None
            embedding_model = await _init_model(embedding_config) if embedding_config else None

            # 按模型的 save_logs 开关挂接调用日志（失败不影响评估）
            if llm is not None and llm_config is not None:
                try:
                    from app.services.llm import create_log_recorder, LLMCallLogger
                    recorder = await create_log_recorder(db, llm_config.id)
                    if recorder.is_enabled():
                        llm = LLMCallLogger(llm, recorder, request_type="chat")
                except Exception as e:
                    logger.warning(f"挂接模型调用日志失败: {e}")

            logger.info(f"初始化后的模型: llm={llm}, embedding_model={embedding_model}")

            # 直接使用 evaluation.metrics 数组中的指标名称
            metric_names = evaluation.metrics or []
            selected_metrics = [(name, METRIC_REGISTRY[name]) for name in metric_names if name in METRIC_REGISTRY]
            need_llm = any(cls.requires_llm for _, cls in selected_metrics)
            need_embedding = any(cls.requires_embedding for _, cls in selected_metrics)

            if not selected_metrics:
                raise ValueError(f"没有可用的评估指标: {metric_names}，可用指标: {sorted(METRIC_REGISTRY.keys())}")

            if need_llm and not llm:
                raise ValueError("评估任务需要配置 LLM 模型（所选指标包含生成阶段指标）")
            if need_embedding and not embedding_model:
                raise ValueError("评估任务需要配置 Embedding 模型（所选指标依赖向量相似度）")

            logger.info(f"评估指标列表: metric_names={metric_names}")

            # 创建评估引擎
            engine = get_metric_engine(
                llm=llm,
                embedding_model=embedding_model,
                metric_names=metric_names
            )
            logger.info(f"评估引擎初始化后的指标: engine.metrics={list(engine.metrics.keys())}")

            # 准备评估数据：根据 reuse_invocation 决定数据来源
            eval_data = []
            for qa in qa_list:
                qa_id = str(qa["id"])
                # 如果有调用结果且 reuse_invocation=True，使用调用结果
                if evaluation.reuse_invocation and qa_id in invocation_results_map:
                    ir = invocation_results_map[qa_id]
                    # 不能用 `ir.answer or qa.get("answer")` 兜底：调用失败时
                    # ir.answer 为空，回落到 QARecord 的静态答案，等于拿
                    # "标准答案"当成 RAG 的输出来打分——失败会被记成满分。
                    # 复用调用结果时，答案只能来自调用结果本身。
                    eval_item = {
                        "id": qa["id"],
                        "question": qa["question"],
                        "answer": ir.answer or "",
                        "contexts": ir.contexts or [],
                        "ground_truth": qa.get("ground_truth"),
                        "retrieval_ids": ir.retrieval_ids or [],
                        "target_chunk_ids": qa.get("target_chunk_ids") or [],
                        "invocation_result_id": ir.id,
                        # RAG 调用本身的失败原因。丢掉它的话，报告里只会看到
                        # "答案为空"这类下游报错，用户根本看不出是 RAG 挂了
                        # 还是评估算错了，排查方向完全被带偏。
                        "invocation_error": ir.error,
                    }
                else:
                    # 使用 QARecord 的原始数据（contexts 存于 snapshot 字段）
                    snapshot = qa.get("snapshot") or {}
                    eval_item = {
                        "id": qa["id"],
                        "question": qa["question"],
                        "answer": qa.get("answer"),
                        "contexts": snapshot.get("contexts"),
                        "ground_truth": qa.get("ground_truth"),
                        "retrieval_ids": [],
                        "target_chunk_ids": qa.get("target_chunk_ids") or [],
                        "invocation_result_id": None,
                        "invocation_error": None,
                    }
                eval_data.append(eval_item)

            # 喂给指标前套上下文预算（不改库里的原始 contexts）。
            # 整页式 RAG 单条能返回 15 万字符，直接拼 prompt 会让上游
            # 超上下文报错或单条耗时数分钟，整批评估失败。
            # 截断统计随样本带着，落库时写进 details。
            for item in eval_data:
                budgeted, stats = apply_context_budget(item.get("contexts"))
                item["contexts"] = budgeted
                item["context_budget"] = stats

            expected_count = len(eval_data)

            # 执行评估
            progress_callback = make_progress_callback(task)

            results = await engine.evaluate_batch(
                qa_records=eval_data,
                batch_size=evaluation.batch_size or 10,
                progress_callback=progress_callback,
                check_cancel=_cancel_checker(evaluation_id),
                on_batch=_batch_persister(evaluation_id, eval_data),
            )

            # 计算汇总。
            # RAG 调用失败的记录必须排除在统计之外：rouge_l/exact_match 这类
            # 纯 Python 指标拿到空答案不报错，只会安静地算个 0 分，于是"压根没
            # 调用成功"被当成"答得极差"计入均值——把 4 条没输出的样本算进分母，
            # 报告就会说 RAG 质量很差，而真相是根本没答。
            scored_idx = [
                i for i, e in enumerate(eval_data) if not e.get("invocation_error")
            ]
            summary = MetricEngine.compute_summary([results[i] for i in scored_idx])
            invocation_errors = [
                e["invocation_error"] for e in eval_data if e.get("invocation_error")
            ]
            # total_records 保持"本次评估的 QA 总数"，另给 scored_records，
            # 两者之差就是没拿到 RAG 输出的样本数，分母才解释得通
            summary["total_records"] = len(eval_data)
            summary["scored_records"] = len(scored_idx)
            if invocation_errors:
                summary["invocation_failed_count"] = len(invocation_errors)
                seen, uniq = set(), []
                for e in invocation_errors:
                    if e not in seen:
                        seen.add(e)
                        uniq.append(e)
                summary["invocation_errors"] = uniq[:5]
            status = await _finalize(
                evaluation_id, summary=summary, expected=len(eval_data)
            )

            return {
                "evaluation_id": evaluation_id,
                "status": status,
                "total_records": len(qa_list),
                "summary": summary
            }

        except TaskCancelled:
            # 用户协作式取消：已逐批落库的样本保留（结果本来就是分批写的），
            # 状态标记 cancelled 并清除取消标志，供重试；重试会先清掉旧结果
            logger.info(f"评估任务 {evaluation_id} 已被用户取消")
            await db.rollback()
            await _finalize(evaluation_id, error="任务已被用户取消", force="cancelled")
            return {"evaluation_id": evaluation_id, "status": "cancelled"}

        except Exception as e:
            # 长 session 很可能就是断在这里，终态一律走独立 session 重试写入；
            # 每条样本都已落库时按 completed 收敛，不推翻真实跑完的分数
            await db.rollback()
            status = await _finalize(
                evaluation_id, error=format_error(e), expected=expected_count
            )
            return {"error": format_error(e), "status": status}


@celery_app.task(bind=True, name="batch_evaluation_task")
def batch_evaluation_task(self, evaluation_ids: List[str]) -> Dict[str, Any]:
    """批量执行评估任务

    Args:
        evaluation_ids: 评估任务ID列表 (UUID字符串格式)
    """
    results = []
    for eval_id in evaluation_ids:
        result = evaluation_task(eval_id)
        results.append(result)
    return {"total": len(evaluation_ids), "results": results}


def _cancel_checker(evaluation_id):
    """批次边界读取消标志的回调。

    必须用独立短 session 并容忍读取失败——远端 PG 会在一次十几分钟的评估中途掐线
    （实测 622s 后 ConnectionDoesNotExistError 正好落在
    SELECT evaluations.cancel_requested 上），一条"读标志"的抖动不该把
    已经算出来的真实分数判成整批失败：取消是可选语义，分数才是这次任务的目的。
    """
    async def check_cancel():
        try:
            async with get_db_context() as session:
                flag = await session.execute(
                    select(Evaluation.cancel_requested).where(Evaluation.id == evaluation_id)
                )
                if flag.scalar():
                    raise TaskCancelled()
        except TaskCancelled:
            raise
        except Exception as exc:
            logger.warning(f"读取取消标志失败，继续评估 {evaluation_id}: {exc}")
    return check_cancel


def _batch_persister(evaluation_id, eval_data: List[Dict[str, Any]]):
    """返回"每批跑完立刻落库"的回调。

    一批 ragas 要几分钟，原先全部批次跑完才写：中途任何异常（包括取消标志读取
    抖动）都会让整段真实打分凭空消失，用户只能从头再烧一遍 token。逐批落库后，
    最坏情况只丢当前这一批。
    """
    async def persist_batch(batch_results, start_index):
        rows = [
            _result_row(evaluation_id, eval_data[start_index + j], result_dict)
            for j, result_dict in enumerate(batch_results)
        ]
        qa_ids = [row["qa_record_id"] for row in rows]

        async def apply(session):
            # 幂等：重试时上一轮可能其实已提交，先删同 qa_record 的旧行，
            # 否则重复样本会把均值算歪（同一条问答被计入两次）
            await session.execute(
                delete(EvalResult).where(
                    EvalResult.eval_id == evaluation_id,
                    EvalResult.qa_record_id.in_(qa_ids),
                )
            )
            session.add_all([EvalResult(**row) for row in rows])

        await commit_with_retry(
            apply,
            get_session=get_db_context,
            label="写入评估结果",
            context=f"eval_id={evaluation_id} 自第 {start_index + 1} 条起 {len(rows)} 条",
        )
    return persist_batch


async def _finalize(
    evaluation_id,
    *,
    summary: Dict[str, Any] = None,
    error: str = None,
    expected: int = 0,
    force: str = None,
    attempts: int = 3,
) -> str:
    """用独立 session 重试写评估终态，正常收尾时按结果表重算而不是只信内存状态。

    两条真实故障：
    1. 远端 PG 在收尾一条 UPDATE 上掐线 → 已逐批落库的分数被记成 failed，
       /analysis 与 compare 全部读不到，几分钟的 ragas token 白烧；
    2. 异常发生在写终态这一步之前，长 session 已经不可用 → 状态永久停在 running。
    所以终态回查 EvalResult 行数：每条样本都有结果就算 completed，
    原始异常只作为 error 记录，不推翻已经真实完成的工作。
    """
    async def apply(db):
        ev = await db.get(Evaluation, evaluation_id)
        if not ev:
            return "missing"
        done = await db.scalar(
            select(func.count(EvalResult.id)).where(EvalResult.eval_id == evaluation_id)
        ) or 0

        if force:
            ev.status = force
            ev.error = error
            ev.cancel_requested = False
        elif ev.cancel_requested:
            ev.status = EvaluationStatus.CANCELLED
            ev.error = error or "任务已被用户取消"
            ev.cancel_requested = False
        elif expected and done >= expected:
            ev.status = EvaluationStatus.COMPLETED
            ev.error = error
            if summary is not None:
                ev.summary = summary
        else:
            ev.status = EvaluationStatus.FAILED
            ev.error = error or f"评估未完成（{done}/{expected}）"

        ev.completed_at = datetime.utcnow()
        return str(ev.status.value if hasattr(ev.status, "value") else ev.status)

    try:
        return await commit_with_retry(
            apply,
            get_session=get_db_context,
            label="写入评估终态",
            context=f"eval_id={evaluation_id}",
            attempts=attempts,
        )
    except Exception as exc:
        logger.error(f"评估终态始终写不进去 {evaluation_id}: {exc}")
        return "unknown"


def _result_row(evaluation_id, eval_item: Dict[str, Any], result_dict: Dict[str, Any]) -> Dict[str, Any]:
    """把一条样本的 MetricResult 集合转成 EvalResult 入库字段。

    明细里必须带上上游调用失败原因与上下文截断统计：两者都是"这条分数为什么
    不可信"的线索，丢了就只剩一个孤立低分，分不清是 RAG 挂了还是证据被裁短了。
    """
    scores_dict = {}
    for metric_name, metric_result in result_dict.items():
        scores_dict[metric_name] = {
            "score": metric_result.score,
            "details": metric_result.details,
            "error": metric_result.error,
        }
    detail_info = {}
    if eval_item.get("invocation_error"):
        detail_info["invocation_error"] = eval_item["invocation_error"]
    if eval_item.get("context_budget"):
        detail_info["context_budget"] = eval_item["context_budget"]

    return {
        "eval_id": evaluation_id,
        "qa_record_id": eval_item["id"],
        "invocation_result_id": eval_item.get("invocation_result_id"),
        "scores": scores_dict,
        "details": detail_info or None,
    }


async def _init_model(model_config: Model) -> Any:
    """初始化模型"""
    params = model_config.params or {}
    model_type = model_config.model_type.lower() if model_config.model_type else ""

    logger.info(f"初始化模型: id={model_config.id}, name={model_config.name}, type={model_type}")
    logger.info(f"模型配置详情: endpoint={model_config.endpoint}, model_name={model_config.model_name}, api_key={'已设置' if model_config.api_key_encrypted else '未设置'}")

    if model_type == "llm":
        # 缺密钥时 ChatOpenAI 抛的是 langchain 自己的校验文本
        # （"Did not find openai_api_key, please add an environment variable…"），
        # 原样落库后用户在详情页读不懂。这里换成一句人话，接口层已有前置守卫，
        # 走到这说明是老数据或绕过了接口直接派的任务。
        if not (model_config.api_key_encrypted or "").strip():
            raise ValueError(
                f"LLM 模型「{model_config.name}」未配置 API Key，无法计算生成类指标；请到模型管理补填密钥后重试"
            )
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=model_config.model_name,
            api_key=model_config.api_key_encrypted,
            base_url=model_config.endpoint,
            temperature=params.get("temperature", 0.7),
            # 出站超时与重试（与 create_llm_from_config 保持一致），防止挂死拖垮 worker
            request_timeout=params.get("timeout", 300),
            max_retries=params.get("max_retries", 2),
            model_kwargs=params.get("extra_params") or {},
        )
        # 验证 LLM 是否正确初始化
        logger.info(f"ChatOpenAI 初始化完成: model={llm.model_name}, api_base={llm.openai_api_base}, has_api_key={bool(llm.openai_api_key)}")
        return llm
    elif model_type == "embedding":
        from langchain_openai import OpenAIEmbeddings
        emb = OpenAIEmbeddings(
            model=model_config.model_name,
            api_key=model_config.api_key_encrypted,
            base_url=model_config.endpoint,
            request_timeout=params.get("timeout", 120),
            max_retries=params.get("max_retries", 2),
        )
        logger.info(f"OpenAIEmbeddings 初始化完成: model={emb.model}, has_api_key={bool(emb.openai_api_key)}")
        return emb
    else:
        logger.warning(f"未知的模型类型: {model_config.model_type}, 模型ID: {model_config.id}")
        return None