# 评估执行路由
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel
from celery.result import AsyncResult

from ...core.database import get_db, get_db_context
from ._common import get_or_404, delete_or_404, start_task
from ...core.utc_datetime import UTCDatetime
from ...core.celery_app import celery_app
from ...models import Evaluation, EvalResult, Dataset, QARecord, InvocationResult, Model
from ...services.diagnostics.trace import (
    RETRIEVAL_STEPS,
    analyze_retrieval_traces,
    channel_rank_of,
    retrieval_step,
)
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
    # 失败原因：/status 一直有返回，但详情响应里没有，
    # 导致评估详情页对 failed 任务什么也显示不出来
    error: Optional[str] = None
    # 协作式取消标志：详情页要靠它判断"取消请求已经发过了但 worker 没动"，
    # 没有这个字段就没法给出强制取消入口（孤儿 running 只能人工改库）
    cancel_requested: Optional[bool] = False
    started_at: Optional[UTCDatetime] = None
    completed_at: Optional[UTCDatetime] = None
    summary: Optional[Dict[str, Any]] = None
    created_at: Optional[UTCDatetime] = None

    class Config:
        from_attributes = True


class MetricConfigCreate(BaseModel):
    metric_id: UUID
    params: Dict[str, Any] = {}
    weight: float = 1.0
    enabled: bool = True


class CompareRequest(BaseModel):
    eval_ids: List[UUID]


def _llm_dependent_metrics(metrics: List[str]) -> List[str]:
    """选中指标里需要真实调用 LLM 的那部分（ragas 生成类指标）。

    以指标注册表的 requires_llm 为准，不在这里另列一份名单——两边口径不一致时，
    守卫会放行算不出分的组合，或拦住本来能跑的纯检索评估。
    """
    from ...services.metrics import METRIC_REGISTRY
    return [m for m in (metrics or []) if getattr(METRIC_REGISTRY.get(m), "requires_llm", False)]


async def require_llm_credentials(db: AsyncSession, metrics: List[str], llm_model_id) -> None:
    """派发前校验 LLM 依赖：缺模型/缺密钥/缺 endpoint 一律 400 拦在接口层。

    此前只在 worker 里炸：ChatOpenAI 抛 langchain 内部校验文本
    （"Did not find openai_api_key, please add an environment variable…"），
    而此时评估已置 running、失败原因原样落库。用户在详情页看到的是一段
    pydantic 报错，分不清是自己模型没配密钥还是评估系统坏了；5 分钟 token
    预算和一次 worker 往返也白白花掉。实测：Qwen3.8-Flash-Next 未存密钥，
    6 个指标里 4 个依赖 LLM，任务 7.8s 后 failed。
    """
    needed = _llm_dependent_metrics(metrics)
    if not needed:
        return
    label = "、".join(needed)
    if not llm_model_id:
        raise HTTPException(status_code=400, detail=f"指标「{label}」需要 LLM，请先选择 LLM 模型")
    model = await db.get(Model, llm_model_id)
    if not model:
        raise HTTPException(status_code=400, detail=f"LLM 模型 {llm_model_id} 不存在")
    if not (model.api_key_encrypted or "").strip():
        raise HTTPException(
            status_code=400,
            detail=f"LLM 模型「{model.name}」未配置 API Key，无法计算「{label}」；请到模型管理补填密钥后再发起",
        )
    if not (model.endpoint or "").strip():
        raise HTTPException(
            status_code=400,
            detail=f"LLM 模型「{model.name}」未配置 endpoint，无法计算「{label}」",
        )


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

    # 获取所有评估任务（一次 in 查询，替代逐 id 的 N+1）
    result = await db.execute(select(Evaluation).where(Evaluation.id.in_(data.eval_ids)))
    found = {str(e.id): e for e in result.scalars().all()}
    evaluations = []
    for eval_id in data.eval_ids:
        evaluation = found.get(str(eval_id))
        if not evaluation:
            raise HTTPException(status_code=404, detail=f"评估任务 {eval_id} 不存在")
        if evaluation.status != "completed":
            raise HTTPException(status_code=400, detail=f"评估任务 {eval_id} 未完成，无法对比")
        evaluations.append(evaluation)

    # 获取所有评估结果，按 qa_record_id 组织。
    # 走 _result_items 而不是裸查 EvalResult：跨系统对比真正要看的是
    # "同一道题在 A 系统漏召、在 B 系统召回了没答好"，只有归因字段能给这个结论。
    all_results = {}
    items_by_eval = {}
    for evaluation in evaluations:
        items = await _result_items(db, evaluation.id)
        items_by_eval[str(evaluation.id)] = items
        for item in items:
            qa_id = item["qa_record_id"]
            if qa_id not in all_results:
                all_results[qa_id] = {
                    "qa_record_id": qa_id,
                    "question": item["question"],
                    "ground_truth": item["ground_truth"],
                    "scores": {},
                    "attribution": {},
                }
            all_results[qa_id]["scores"][evaluation.name] = item["metric_scores"]
            all_results[qa_id]["attribution"][evaluation.name] = classify_attribution(item)

    # 构建对比数据
    comparison_data = list(all_results.values())

    # 构建汇总数据
    summary_data = {}
    for evaluation in evaluations:
        summary_data[evaluation.name] = evaluation.summary or {}

    # 各评估背后的 RAG 系统名：对比页面上 eval name 常常叫 "xxx-v1"，
    # 不带系统名就分不清哪一列是谁
    from ...models import RAGSystem
    sys_ids = [e.rag_system_id for e in evaluations if e.rag_system_id]
    sys_names = {}
    if sys_ids:
        rows = await db.execute(select(RAGSystem).where(RAGSystem.id.in_(sys_ids)))
        sys_names = {str(r.id): r.name for r in rows.scalars().all()}

    return {
        "evaluations": [
            {
                "id": str(e.id),
                "name": e.name,
                "metrics": e.metrics or [],
                "summary": e.summary,
                "rag_system_id": str(e.rag_system_id) if e.rag_system_id else None,
                "rag_system_name": sys_names.get(str(e.rag_system_id)) if e.rag_system_id else None,
                "attribution": attribution_summary(items_by_eval[str(e.id)]),
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

    # 生成类指标的 LLM 依赖在创建时就校验，别等派发后在 worker 里炸
    await require_llm_credentials(db, data.metrics, data.llm_model_id)

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
    limit: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取评估任务列表（limit 用于仪表盘等只需最近 N 条的场景）"""
    query = select(Evaluation)
    if status:
        query = query.where(Evaluation.status == status)
    if dataset_id:
        query = query.where(Evaluation.dataset_id == dataset_id)
    query = query.order_by(Evaluation.created_at.desc())
    if limit:
        # 运行时钳制，防止 limit 过大全表拉取
        query = query.limit(min(limit, 500))
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/daily-stats")
async def get_daily_stats():
    """系统统计（Dashboard 首页数据）"""
    from sqlalchemy import text

    async with get_db_context() as db:
        datasets_count = (await db.execute(text("SELECT COUNT(*) as count FROM datasets"))).scalar()
        qa_count = (await db.execute(text("SELECT COUNT(*) as count FROM qa_records"))).scalar()
        eval_row = (await db.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'completed') as completed,
                COUNT(*) FILTER (WHERE status = 'running') as running,
                COUNT(*) FILTER (WHERE status = 'pending') as pending,
                COUNT(*) FILTER (WHERE status = 'failed') as failed
            FROM evaluations
        """))).mappings().one()
        rag_count = (await db.execute(text("SELECT COUNT(*) as count FROM rag_systems"))).scalar()
        model_row = (await db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE model_type = 'llm') as llm,
                COUNT(*) FILTER (WHERE model_type = 'embedding') as embedding,
                COUNT(*) FILTER (WHERE model_type = 'reranker') as reranker
            FROM models
        """))).mappings().one()

    return {
        "total_datasets": datasets_count,
        "total_qa_records": qa_count,
        "evaluations": {
            "total": eval_row["total"],
            "completed": eval_row["completed"],
            "running": eval_row["running"],
            "pending": eval_row["pending"],
            "failed": eval_row["failed"],
        },
        "total_rag_systems": rag_count,
        "models": {
            "llm": model_row["llm"],
            "embedding": model_row["embedding"],
            "reranker": model_row["reranker"],
        },
    }


@router.get("/{eval_id}", response_model=EvaluationResponse)
async def get_evaluation(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取评估任务详情"""
    evaluation = await get_or_404(db, Evaluation, eval_id, "评估任务不存在")
    return evaluation


@router.delete("/{eval_id}")
async def delete_evaluation(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除评估任务"""
    await delete_or_404(db, Evaluation, eval_id, "评估任务不存在")
    await db.commit()
    return {"message": "删除成功"}


@router.post("/{eval_id}/run")
async def run_evaluation(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """执行评估任务"""
    evaluation = await get_or_404(db, Evaluation, eval_id, "评估任务不存在")

    if evaluation.status == "running":
        raise HTTPException(status_code=400, detail="评估任务正在执行中")

    # 创建之后密钥可能被删或改，派发前按当前库里的指标与模型再校验一次
    await require_llm_credentials(db, evaluation.metrics, evaluation.llm_model_id)

    # 置运行中并派发；broker 不可达时状态自动回滚，不会永久卡在 running
    task = await start_task(db, evaluation, lambda: evaluation_task.delay(str(eval_id)))

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
    evaluation = await get_or_404(db, Evaluation, eval_id, "评估任务不存在")

    return {
        "eval_id": str(eval_id),
        "status": evaluation.status,
        "progress": evaluation.progress,
        "error": evaluation.error
    }


# 根因分析阈值：低于该均值视为该指标"不达标"
ANALYSIS_WEAK_THRESHOLD = 0.6

# 逐条归因分桶：一条低分样本先要判断"断在哪一步"，再看具体指标
ATTRIBUTION_BUCKETS = (
    "call_failed", "retrieval_miss", "retrieved_but_answer_weak",
    "retrieved_ok", "no_gold", "no_retrieval_trace",
)


def classify_attribution(item: Dict[str, Any]) -> str:
    """把一条评估结果归到 RAG 链路的某一环，用于 badcase 分步定位。

    顺序即诊断顺序：上游调用没成功，后面所有分数都不必再看；
    gold 没进检索轨迹，低分出在召回而不是生成；召回对了才轮到生成。
    """
    if item.get("invocation_error"):
        return "call_failed"
    scores = item.get("metric_scores") or {}
    gen = [
        float(v["score"]) for k, v in scores.items()
        if isinstance(v, dict) and v.get("score") is not None and not v.get("error")
        and (str(k).startswith("answer_") or k == "faithfulness")
    ]
    gen_avg = sum(gen) / len(gen) if gen else None
    gold_weak = gen_avg is not None and gen_avg < ANALYSIS_WEAK_THRESHOLD
    if item.get("gold_hit") is None:
        return "no_retrieval_trace" if item.get("target_chunk_ids") else "no_gold"
    if not item["gold_hit"]:
        return "retrieval_miss"
    return "retrieved_but_answer_weak" if gold_weak else "retrieved_ok"


def attribution_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """按环统计样本数与占比，占比最高的问题环即聚合层根因。"""
    counts = {b: 0 for b in ATTRIBUTION_BUCKETS}
    for item in items:
        counts[classify_attribution(item)] += 1
    n = len(items) or 1
    return {
        "total": len(items),
        "counts": counts,
        "ratios": {k: round(v / n, 4) for k, v in counts.items()},
        # 检索漏召占全部样本的比例，用来判断"根因在召回"这一结论的强度
        "retrieval_miss_rate": round(counts["retrieval_miss"] / n, 4),
        "call_failed_rate": round(counts["call_failed"] / n, 4),
    }


async def _result_items(db: AsyncSession, eval_id: UUID) -> List[Dict[str, Any]]:
    """评估结果 + 逐条归因字段（gold / 检索轨迹 / 上游调用错误）。

    /results 与 /analysis 共用：归因要看的字段只存在于 InvocationResult 和
    QARecord 上，任何一处单独拼都会和另一处口径不一致。
    """
    rows = (await db.execute(
        select(EvalResult, QARecord)
        .join(QARecord, EvalResult.qa_record_id == QARecord.id)
        .where(EvalResult.eval_id == eval_id)
        .order_by(EvalResult.id)
    )).all()

    # 关联的调用结果：retrieval_ids / invocation_error 只存在这张表上
    inv_map = {}
    inv_ids = [er.invocation_result_id for er, _ in rows if er.invocation_result_id]
    if inv_ids:
        inv_rows = await db.execute(
            select(InvocationResult).where(InvocationResult.id.in_(inv_ids))
        )
        inv_map = {str(ir.id): ir for ir in inv_rows.scalars().all()}

    items = []
    for er, qr in rows:
        ir = inv_map.get(str(er.invocation_result_id)) if er.invocation_result_id else None
        retrieval_ids = list(ir.retrieval_ids or []) if ir else []
        gold_ids = [str(g) for g in (qr.target_chunk_ids or [])]
        items.append({
            "id": str(er.id),
            "qa_record_id": str(er.qa_record_id),
            "question": qr.question,
            "answer": qr.answer,
            "ground_truth": qr.ground_truth,
            "metric_scores": er.scores or {},
            "details": er.details,
            # —— 逐条归因字段 ——
            "target_chunk_ids": gold_ids,
            "retrieval_ids": retrieval_ids,
            "contexts_count": len(ir.contexts or []) if ir else None,
            # gold 是否被召回：false 说明这条低分出在检索阶段，不是生成阶段。
            # 只有在拿得到检索轨迹时才判定——ir 为空或 retrieval_ids 为 None
            # （老系统不回传 id）时给 None，表示"无从判断"而不是"没召回"。
            "gold_hit": (
                bool(set(gold_ids) & {str(r) for r in retrieval_ids})
                if gold_ids and ir is not None and ir.retrieval_ids is not None
                else None
            ),
            "invocation_error": ir.error if ir else None,
            # 检索轨迹（通道排序/定位轮次/兜底标记）。老系统没回传时为 None，
            # 归因层据此把"没轨迹"和"轨迹显示各通道都没命中"分开——
            # 前者是接入问题，后者才是检索本身的问题。
            "trace": (ir.trace if ir else None) or None,
            "created_at": er.created_at.isoformat() if er.created_at else None,
        })
    return items


def _trace_summary(item: Dict[str, Any]) -> Dict[str, Any]:
    """给列表用的轨迹摘要：通道规模、断点、gold 在各路的最好名次。

    完整 trace 单条可到几十 KB，列表页一次几百条没必要全带上；
    要看原文走 /results/{id}/trace。
    """
    trace = item.get("trace") or {}
    channels = trace.get("channels") or {}
    gold = [str(g) for g in (item.get("target_chunk_ids") or [])]
    return {
        "has_trace": bool(trace),
        "mode": trace.get("mode"),
        "fallback": trace.get("fallback"),
        "channels": {name: len(ids) for name, ids in channels.items()},
        "rounds": trace.get("rounds_total") or len(trace.get("rounds") or []),
        "unavailable": trace.get("unavailable") or {},
        "gold_channel_ranks": channel_rank_of(gold, channels) if gold else {},
        "retrieval_step": retrieval_step(item),
    }


@router.get("/{eval_id}/analysis")
async def get_evaluation_analysis(
    eval_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """根因分析：指标均值（检索/生成两阶段）+ 逐条分步归因分布。

    规则（RAG 评估的标准诊断链路）：
    - 上游调用失败占比最高 → 根因在接入层，指标均值不可信
    - gold 漏召占比最高 → 根因在召回：上下文本身没找对，生成再好也没用
    - 检索强 + faithfulness 弱 → 生成阶段没照着上下文答（幻觉/自由发挥）
    - faithfulness 强 + answer_relevancy 弱 → 答非所问（问题理解偏差）
    - 两阶段都强 + correctness 弱 → 知识覆盖缺口（语料缺内容）
    """
    # 仅做存在性校验（404），后续只读结果表
    await get_or_404(db, Evaluation, eval_id, "评估任务不存在")

    items = await _result_items(db, eval_id)
    if not items:
        raise HTTPException(status_code=400, detail="评估尚无结果，无法分析")

    from ...services.metrics.engine import METRIC_REGISTRY

    # 逐指标求均值（跳过 error 样本）
    metric_values: Dict[str, List[float]] = {}
    for item in items:
        for name, entry in (item["metric_scores"] or {}).items():
            if isinstance(entry, dict) and entry.get("score") is not None and not entry.get("error"):
                metric_values.setdefault(name, []).append(float(entry["score"]))
    metric_means = {
        name: sum(vals) / len(vals)
        for name, vals in metric_values.items()
        if vals
    }

    def _stage_of(metric_name: str) -> tuple:
        cls = METRIC_REGISTRY.get(metric_name)
        if not cls:
            return ("unknown", "unknown")
        return (cls.eval_stage, cls.category)

    retrieval_scores = {n: s for n, s in metric_means.items() if _stage_of(n) == ("process", "retrieval")}
    generation_scores = {n: s for n, s in metric_means.items() if _stage_of(n)[0] == "result"}

    def _avg(d: Dict[str, float]) -> Optional[float]:
        return sum(d.values()) / len(d) if d else None

    retrieval_avg = _avg(retrieval_scores)
    generation_avg = _avg(generation_scores)
    weak_metrics = sorted(
        [n for n, s in metric_means.items() if s < ANALYSIS_WEAK_THRESHOLD],
        key=lambda n: metric_means[n]
    )

    # 根因定位：先看逐条归因（哪一环断的样本最多），再用指标均值兜底
    attribution = attribution_summary(items)
    buckets = attribution["counts"]
    # 通道级下钻：只有 retrieval_ids 时归因止步于"漏召"，
    # 有了 trace 才能分清"各通道都没捞到"和"捞到了却在融合里被挤掉"
    trace_analysis = analyze_retrieval_traces(items)
    diagnosable = (buckets["retrieval_miss"] + buckets["retrieved_but_answer_weak"]
                   + buckets["retrieved_ok"])
    root_cause: Dict[str, Any] = {}
    recommendations: List[str] = []

    if attribution["call_failed_rate"] >= 0.3:
        root_cause = {
            "stage": "invocation", "confidence": "high",
            "evidence": f"{buckets['call_failed']}/{attribution['total']} 条上游调用失败",
        }
        recommendations.append("先修接入层：调用失败样本的检索/生成指标都是空值，均值不可用于诊断")
        recommendations.append("在调用批次详情按失败原因重试，或换 request_timeout 更大的系统配置后重跑")
    elif diagnosable and buckets["retrieval_miss"] / diagnosable >= 0.5:
        root_cause = {
            "stage": "retrieval", "confidence": "high",
            "evidence": (f"有检索轨迹的 {diagnosable} 条里 {buckets['retrieval_miss']} 条 "
                         f"gold 分片未被召回"),
        }
        recommendations.append("低分主因是召回漏召，不是生成：先动检索侧（分片、top-k、重排、索引类型）")
        recommendations.append("按 /results?metric=recall_k&max_score=0 导出漏召样本，核对其 gold 分片是否真的存在于知识库")
        if trace_analysis["coverage"]["with_channels"]:
            # 漏召再往下拆一层：改融合配比还是改索引，成本完全不同
            if (trace_analysis["fusion_loss_rate"] or 0) >= 0.3:
                root_cause["sub_stage"] = "fusion"
                recommendations.append(
                    f"其中 {trace_analysis['step_counts']['lost_in_fusion']} 条某一路已经捞到 gold，"
                    f"是融合/重排把它们挤掉的（fusion_loss_rate={trace_analysis['fusion_loss_rate']}）："
                    f"先调通道权重或加 reranker，别急着改分片"
                )
                if trace_analysis["best_channel"]:
                    recommendations.append(
                        f"单通道最好的一路是 {trace_analysis['best_channel']}，"
                        f"可用 ?channels= 只跑这一路做对照，确认是配比问题而不是召回问题"
                    )
            elif (trace_analysis["all_channel_miss_rate"] or 0) >= 0.5:
                root_cause["sub_stage"] = "index"
                recommendations.append(
                    f"{trace_analysis['step_counts']['channel_all_miss']} 条是所有通道都没有 gold："
                    f"往分片粒度、索引覆盖和 query 理解上找，动融合配比不会有用"
                )
            unavailable = {}
            for item in items:
                for name, why in ((item.get("trace") or {}).get("unavailable") or {}).items():
                    unavailable[name] = why
            if unavailable:
                recommendations.append(
                    "有通道在评测期间没跑成（" + "；".join(f"{k}: {v}" for k, v in unavailable.items()) + "），"
                    "该通道的召回数字是假的 0，先修复再接着比"
                )
    elif diagnosable and diagnosable - buckets["retrieval_miss"] >= buckets["retrieval_miss"] \
            and buckets["retrieved_but_answer_weak"] > 0 \
            and buckets["retrieved_but_answer_weak"] / (diagnosable - buckets["retrieval_miss"]) >= 0.5:
        root_cause = {
            "stage": "generation", "confidence": "high",
            "evidence": (f"gold 已召回的样本里 {buckets['retrieved_but_answer_weak']} 条"
                         f"生成指标仍不达标"),
        }
        recommendations.append("上下文里有答案但没答对：检查提示词是否要求仅依据资料作答、答案是否被上下文长度预算截断（见 details.context_budget）")
    elif retrieval_avg is not None and retrieval_avg < ANALYSIS_WEAK_THRESHOLD:
        root_cause = {
            "stage": "retrieval",
            "confidence": "high" if retrieval_avg < 0.4 else "medium",
            "evidence": f"检索类指标均值 {round(retrieval_avg, 3)}",
        }
        recommendations.append("检索阶段是瓶颈：检查分片策略（chunk 大小/重叠）与向量模型是否匹配语料领域")
        recommendations.append("尝试提高召回 top-k 并用 reranker 重排，观察 context_precision 是否回升")
        if "context_recall" in retrieval_scores and \
           retrieval_scores["context_recall"] < ANALYSIS_WEAK_THRESHOLD:
            recommendations.append("context_recall 偏低说明知识库缺少相关内容，建议补充同步数据源文档")
    elif buckets["no_retrieval_trace"] == attribution["total"]:
        root_cause = {
            "stage": "unknown", "confidence": "low",
            "evidence": "所有样本都没有检索轨迹（retrieval_ids 为空）",
        }
        recommendations.append("被评估的 RAG 系统未回传命中的分片 id，无法做逐环归因：在接入层补齐 retrieval_ids（或改用带分片 id 的返回格式）")
    else:
        faith = metric_means.get("faithfulness")
        relev = metric_means.get("answer_relevancy")
        correct = metric_means.get("answer_correctness") or metric_means.get("exact_match")
        if faith is not None and faith < ANALYSIS_WEAK_THRESHOLD:
            root_cause = {"stage": "generation", "confidence": "high",
                          "evidence": f"faithfulness 均值 {round(faith, 3)}"}
            recommendations.append("上下文召回尚可但生成未遵循上下文（疑似幻觉）：在提示词中强制\"仅依据给定资料回答\"，并降低 temperature")
        elif relev is not None and relev < ANALYSIS_WEAK_THRESHOLD:
            root_cause = {"stage": "generation", "confidence": "medium",
                          "evidence": f"answer_relevancy 均值 {round(relev, 3)}"}
            recommendations.append("答案忠实但偏离问题：建议增加 query 改写/分解步骤，或在系统提示中强调切题")
        elif correct is not None and correct < ANALYSIS_WEAK_THRESHOLD:
            root_cause = {"stage": "knowledge", "confidence": "medium",
                          "evidence": f"answer_correctness 均值 {round(correct, 3)}"}
            recommendations.append("流程指标健康但正确性不足：知识库内容缺口，建议核对数据集 ground truth 覆盖并补充语料")
        else:
            root_cause = {"stage": "none", "confidence": "high", "evidence": "各阶段指标均达标"}
            recommendations.append("各阶段指标均达标，当前配置可作为基线；可扩测更多困难样本（multi_context/reasoning 类）验证上限")

    return {
        "eval_id": str(eval_id),
        "analysis": {
            "metric_means": {k: round(v, 4) for k, v in metric_means.items()},
            "retrieval_analysis": {
                "average": round(retrieval_avg, 4) if retrieval_avg is not None else None,
                "metrics": {k: round(v, 4) for k, v in retrieval_scores.items()},
            },
            "generation_analysis": {
                "average": round(generation_avg, 4) if generation_avg is not None else None,
                "metrics": {k: round(v, 4) for k, v in generation_scores.items()},
            },
            # 逐环归因：接入了检索轨迹的评估才能给出"断在哪一步"的分布
            "attribution": attribution,
            # 通道级下钻：每路各自的 hit/recall，以及漏召到底断在索引还是融合
            "retrieval_trace_analysis": trace_analysis,
            "weak_metrics": weak_metrics,
            "root_cause": root_cause,
            "recommendations": recommendations,
        },
    }


@router.get("/{eval_id}/results")
async def get_evaluation_results(
    eval_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    metric: Optional[str] = Query(None, description="按该指标筛 badcase，配合 min_score/max_score"),
    min_score: Optional[float] = Query(None, ge=0, le=1),
    max_score: Optional[float] = Query(None, ge=0, le=1),
    only_errors: bool = Query(False, description="只看打分失败或上游调用失败的样本"),
    attribution: Optional[str] = Query(
        None, enum=list(ATTRIBUTION_BUCKETS),
        description="只看归到该环的样本，如 retrieval_miss=gold 未召回"),
    step: Optional[str] = Query(
        None, enum=list(RETRIEVAL_STEPS),
        description="在归因之上再下一层：漏召是各通道都没捞到（channel_all_miss，改索引）"
                    "还是捞到了被融合挤掉（lost_in_fusion，调配比/重排）"),
    db: AsyncSession = Depends(get_db)
):
    """获取评估结果，包含每条 QA 记录的详细信息和得分

    badcase 归因所需字段一并返回：gold 分片（target_chunk_ids）、实际命中的
    分片（retrieval_ids）、是否命中（gold_hit）与上游调用失败原因。缺了这些，
    低分样本只能看到"分数低"，判断不了是检索没召回、还是召回了没答好。
    """
    evaluation = await get_or_404(db, Evaluation, eval_id, "评估任务不存在")
    items = await _result_items(db, eval_id)
    for item in items:
        item["attribution"] = classify_attribution(item)
        # 列表只带轨迹摘要，完整 trace 交给 /results/{id}/trace：
        # 一次拉 200 条原始轨迹能有几十 MB，前端也用不到全部通道排序
        item["trace_summary"] = _trace_summary(item)
        item.pop("trace", None)

    def _score_of(item: Dict[str, Any]) -> Optional[float]:
        entry = item["metric_scores"].get(metric)
        if isinstance(entry, dict):
            return entry.get("score")
        if isinstance(entry, (int, float)):
            return float(entry)
        return None

    # 过滤在内存完成：score 存在 JSON 列里，跨方言（PG JSONB / SQLite JSON）
    # 取 JSON path 再比大小的写法不通用，而单批次评估样本量本就有限。
    if metric or only_errors or attribution or step:
        filtered = []
        for item in items:
            if attribution and item["attribution"] != attribution:
                continue
            if step and item["trace_summary"]["retrieval_step"] != step:
                continue
            if only_errors:
                has_metric_error = any(
                    isinstance(v, dict) and v.get("error")
                    for v in (item["metric_scores"] or {}).values()
                )
                if not (has_metric_error or item["invocation_error"]):
                    continue
            if metric:
                s = _score_of(item)
                if s is None:
                    continue
                if min_score is not None and s < min_score:
                    continue
                if max_score is not None and s > max_score:
                    continue
            filtered.append(item)
        items = filtered

    total = len(items)
    return {
        "eval_id": str(eval_id),
        "summary": evaluation.summary,
        "total": total,
        "results": items[skip:skip + limit],
    }


@router.get("/{eval_id}/results/{result_id}/trace")
async def get_result_trace(
    eval_id: UUID,
    result_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """单条 badcase 的完整检索轨迹：各通道排序、树定位轮次、兜底标记。

    列表接口只给摘要（一次 200 条原始轨迹能到几十 MB），下钻某一条时才取全量。
    同时把 gold 在每一路的名次一并算好——人来看"到底哪一步断的"，
    最想先知道的就是"它其实被谁捞到过"。
    """
    await get_or_404(db, Evaluation, eval_id, "评估任务不存在")
    items = await _result_items(db, eval_id)
    item = next((it for it in items if it["id"] == str(result_id)), None)
    if item is None:
        raise HTTPException(status_code=404, detail="该评估下没有这条结果")
    gold = [str(g) for g in (item.get("target_chunk_ids") or [])]
    channels = (item.get("trace") or {}).get("channels") or {}
    return {
        "eval_id": str(eval_id),
        "result_id": str(result_id),
        "question": item.get("question"),
        "target_chunk_ids": gold,
        "retrieval_ids": item.get("retrieval_ids") or [],
        "retrieval_step": retrieval_step(item),
        "gold_channel_ranks": channel_rank_of(gold, channels),
        "trace": item.get("trace"),
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
    force: bool = Query(False, description="worker 不在运行时直接把库里的孤儿任务落成 cancelled"),
    db: AsyncSession = Depends(get_db)
):
    """取消评估任务

    Args:
        eval_id: 评估任务ID
        task_id: 保留参数（旧客户端兼容）。不再 SIGKILL worker——硬杀会让
            DB 状态永久停留 running；统一走协作式取消，由 worker 落库 cancelled
        force: 协作式取消依赖 worker 还活着。broker/Redis 抖动时任务可能压根
            没被领取（实测：worker 报 "Couldn't ack" 后再没有 evaluation_task
            日志），此时置标志等于什么都没发生，状态永远停在 running，
            retry 又只收 failed/cancelled → 只能人工改库。force 走纯库侧终结。
    """
    evaluation = await get_or_404(db, Evaluation, eval_id, "评估任务不存在")

    if evaluation.status != "running":
        raise HTTPException(status_code=400, detail="评估任务未在运行中，无法取消")

    if force:
        evaluation.status = "cancelled"
        evaluation.error = "评估已被用户强制取消（worker 未领取或未在运行）"
        evaluation.cancel_requested = False
        evaluation.completed_at = datetime.utcnow()
        await db.commit()
        return {"message": "评估任务已强制取消", "eval_id": str(eval_id), "forced": True}

    # 协作式取消：worker 在批次边界检测到该标志后停止并落库 cancelled。
    # 此前"只改库不杀任务"是假取消——任务继续跑完并把状态覆写回 completed
    evaluation.cancel_requested = True
    await db.commit()

    return {
        "message": "取消请求已提交，任务将在当前批次结束后停止",
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
    evaluation = await get_or_404(db, Evaluation, eval_id, "评估任务不存在")

    # 只允许重试失败的任务
    if evaluation.status not in ("failed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"只有失败或取消的任务才能重试，当前状态: {evaluation.status}"
        )

    # 更新 reuse_invocation 设置
    evaluation.reuse_invocation = reuse_invocation

    # 重试同样先校验 LLM 依赖：上次失败很可能就是缺密钥，
    # 不拦下来只会把任务再送进 worker 转一圈继续 failed
    await require_llm_credentials(db, evaluation.metrics, evaluation.llm_model_id)

    # 清除之前的错误信息和时间
    evaluation.error = None
    evaluation.started_at = None
    evaluation.completed_at = None
    evaluation.progress = 0
    evaluation.cancel_requested = False

    # 删除之前的评估结果（如果需要重新评估）
    from sqlalchemy import delete
    await db.execute(delete(EvalResult).where(EvalResult.eval_id == eval_id))

    # 置运行中并派发。原先"先提交 pending → delay → 再提交 running"存在竞态：
    # 秒级完成的 worker 写入 completed 会被随后的 running 覆盖，状态永久卡死
    task = await start_task(db, evaluation, lambda: evaluation_task.delay(str(eval_id)),
                            fallback_value="pending")

    return {
        "message": "评估任务已重新启动",
        "eval_id": str(eval_id),
        "task_id": task.id,
        "reuse_invocation": reuse_invocation
    }