# LLM 深度数据分析（可选层）
#
# 规则画像（profiling.py）回答"长什么样"；本模块回答"内容到底是什么、好不好用"。
# 三种模式：
#   off    —— 不调 LLM（默认）
#   sample —— 均匀抽样 N 条，一次调用生成整体分析（快、便宜，适合浏览）
#   full   —— 全量分批过 LLM：每批打主题/质量标签 + 末尾一次汇总（准、贵）
#
# completer 抽象成 (prompt) -> str，便于单测注入假 LLM；真实调用走
# services.llm.llm_client 创建的 ChatOpenAI。
import json
import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

Completer = Callable[[str], Awaitable[str]]

# full 模式批量与上限：单批条数、最多批次数（防误触全量大模型账单）
FULL_BATCH_SIZE = 20
FULL_MAX_BATCHES = 100
# 单条正文送 LLM 前的截断长度（字符）
MAX_RECORD_CHARS = 2000


def _compact_record(payload: Dict[str, Any]) -> str:
    """把一条样本压成给 LLM 看的紧凑文本"""
    if not isinstance(payload, dict):
        return str(payload)[:MAX_RECORD_CHARS]
    parts: List[str] = []
    for key, value in payload.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = str(value)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 600:
            text = text[:600] + "…"
        parts.append(f"{key}: {text}")
    joined = "\n".join(parts)
    return joined[:MAX_RECORD_CHARS]


def build_sample_prompt(records: Sequence[Dict[str, Any]], context: Dict[str, Any]) -> str:
    rendered = "\n\n".join(
        f"[{i + 1}] {_compact_record(r)}" for i, r in enumerate(records)
    )
    return f"""你是数据集画像专家。下面是从一个训练数据集中均匀抽取的 {len(records)} 条样本（数据集总条数约 {context.get('total', '未知')}，主格式 {context.get('format', '未知')}）。

请通读这些样本，输出一份让「没接触过这个数据集的人」能一眼看懂的分析。只输出 JSON，不要多余文字，结构如下：
{{
  "what_is_it": "这个数据集是什么（1-2 句人话）",
  "content_summary": "内容主题与覆盖范围（3-5 句）",
  "style_and_format": "样本的写作风格/结构特征（如指令-回答配对、多轮对话、带工具调用等）",
  "quality_impression": "从样本看出的质量印象（语言流畅度、信息密度、格式一致性等）",
  "strengths": ["优势1", "优势2"],
  "weaknesses": ["不足1"],
  "suggested_uses": ["适合的训练用途1", "用途2"],
  "risks": ["潜在风险/偏见/敏感内容等，没有则为空数组"],
  "representative_examples": [1, 5],
  "notes": "其他值得知道的观察"
}}

样本：
{rendered}"""

FULL_BATCH_PROMPT = """你是数据集标注员。逐条看下面 {n} 条训练数据样本，为每条输出一个对象，只输出 JSON 数组，元素格式：
{{"idx": 序号, "topics": ["主题标签1", "主题标签2"], "quality": 1到5的整数, "issue": "若有明显问题写一句话，没有则空字符串"}}

样本：
{samples}"""

FULL_SUMMARY_PROMPT = """你是数据集画像专家。对一个训练数据集的全部 {n} 条样本分批标注后得到以下聚合结果：

各批主题标签计数：{topics}
质量分分布(1-5)：{quality_hist}
常见问题：{issues}
数据集统计：{stats}

请输出 JSON（不要多余文字），让「没接触过这个数据集的人」一眼看懂：
{{
  "what_is_it": "这个数据集是什么（1-2 句）",
  "content_summary": "主题分布与覆盖范围（3-5 句）",
  "style_and_format": "结构/风格特征",
  "quality_impression": "基于全量标注的质量结论",
  "strengths": ["优势"],
  "weaknesses": ["不足"],
  "suggested_uses": ["适合的训练用途"],
  "risks": ["风险"],
  "notes": "其他观察"
}}"""


def _parse_json_loose(text: str) -> Any:
    """LLM 输出容错解析：剥 ```json 围栏、取首个 {/[ 到最后一个 }/] 的片段"""
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    if cleaned[:1] not in "[{":
        start = min((i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0), default=-1)
        if start >= 0:
            end = max(cleaned.rfind("}"), cleaned.rfind("]"))
            cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


def _text_from_reply(reply: Any) -> str:
    """兼容 str / AIMessage（langchain）等多种返回"""
    if isinstance(reply, str):
        return reply
    content = getattr(reply, "content", None)
    if isinstance(content, str):
        return content
    return str(reply)


async def analyze_sample(
    records: Sequence[Dict[str, Any]],
    context: Dict[str, Any],
    complete: Completer,
) -> Dict[str, Any]:
    """sample 模式：抽样一次调用"""
    prompt = build_sample_prompt(records, context)
    reply = await complete(prompt)
    data = _parse_json_loose(_text_from_reply(reply))
    if not isinstance(data, dict):
        raise ValueError("LLM 抽样分析返回的不是 JSON 对象")
    data["mode"] = "sample"
    data["analyzed_records"] = len(records)
    return data


async def analyze_full(
    payloads: Sequence[Dict[str, Any]],
    context: Dict[str, Any],
    complete: Completer,
    batch_size: int = FULL_BATCH_SIZE,
    max_batches: int = FULL_MAX_BATCHES,
    batch_progress: Optional[Callable[[int, int], Any]] = None,
) -> Dict[str, Any]:
    """full 模式：分批逐条标注 + 汇总。返回每批原始标注也一并保留（per_record_batches）"""
    batches: List[List[Dict[str, Any]]] = []
    for i in range(0, len(payloads), batch_size):
        if len(batches) >= max_batches:
            break
        batches.append(list(payloads[i:i + batch_size]))

    topic_counter: Dict[str, int] = {}
    quality_hist = {str(q): 0 for q in range(1, 6)}
    issues: List[str] = []
    per_record: List[Dict[str, Any]] = []

    for bi, batch in enumerate(batches):
        rendered = "\n\n".join(f"[{i}] {_compact_record(r)}" for i, r in enumerate(batch))
        prompt = FULL_BATCH_PROMPT.format(n=len(batch), samples=rendered)
        reply = await complete(prompt)
        try:
            items = _parse_json_loose(_text_from_reply(reply))
            if isinstance(items, dict):
                items = items.get("items") or items.get("labels") or []
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(f"full 模式第 {bi + 1} 批解析失败，跳过: {exc}")
            items = []
        if not isinstance(items, list):
            items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            for topic in (item.get("topics") or []):
                topic = str(topic).strip()
                if topic:
                    topic_counter[topic] = topic_counter.get(topic, 0) + 1
            try:
                q = int(item.get("quality"))
            except (TypeError, ValueError):
                q = 3
            q = max(1, min(5, q))
            quality_hist[str(q)] += 1
            issue = str(item.get("issue") or "").strip()
            if issue and len(issues) < 50:
                issues.append(issue)
            per_record.append({
                "batch": bi, "idx": item.get("idx"),
                "topics": item.get("topics") or [], "quality": q, "issue": issue or None,
            })
        if batch_progress:
            try:
                batch_progress(bi + 1, len(batches))
            except Exception:  # 进度回调失败不影响分析
                pass

    stats = context.get("stats") or {}
    summary_prompt = FULL_SUMMARY_PROMPT.format(
        n=len(per_record),
        topics=dict(sorted(topic_counter.items(), key=lambda kv: -kv[1])[:30]),
        quality_hist=quality_hist,
        issues=issues[:20],
        stats=stats,
    )
    reply = await complete(summary_prompt)
    try:
        data = _parse_json_loose(_text_from_reply(reply))
        if not isinstance(data, dict):
            data = {}
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(f"full 模式汇总解析失败: {exc}")
        data = {}

    data.update({
        "mode": "full",
        "analyzed_records": len(per_record),
        "topic_counts": dict(sorted(topic_counter.items(), key=lambda kv: -kv[1])[:30]),
        "quality_hist": quality_hist,
        "issues": issues[:50],
        "per_record": per_record,
    })
    return data


async def resolve_completer(
    db, llm_model_id: Optional[Any] = None
) -> Optional[Completer]:
    """解析出可用的 LLM completer；没有可用模型时返回 None（调用方降级为仅规则画像）"""
    from sqlalchemy import select
    from ...models.model import Model
    from ...services.llm.llm_client import create_llm_from_config

    if llm_model_id:
        model = (await db.execute(select(Model).where(Model.id == llm_model_id))).scalar_one_or_none()
        if model is None:
            raise ValueError(f"LLM 模型 {llm_model_id} 不存在")
        if model.model_type != "llm":
            raise ValueError(f"模型 {model.name} 不是 LLM 类型")
    else:
        model = (await db.execute(
            select(Model).where(Model.model_type == "llm", Model.status == "active")
            .order_by(Model.is_default.desc())
        )).scalars().first()
        if model is None:
            return None

    llm = await create_llm_from_config(model)

    async def complete(prompt: str) -> str:
        reply = await llm.ainvoke(prompt)
        return _text_from_reply(reply)

    return complete
