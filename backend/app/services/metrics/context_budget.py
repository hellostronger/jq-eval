# 评估阶段的上下文 token 预算
#
# 为什么需要：调用批次存的是 RAG 系统原样返回的 contexts。整页式系统
# （TreeWiki / PageIndex 这类"按页喂全文"的实现）单条问答能返回 8~10 页原文，
# 合计 15 万字符 ≈ 4~5 万 token。直接送进 faithfulness / context_precision
# 这类把 contexts 全量拼进 prompt 的指标，结果是上游报
# "context length exceeded" 或单条打分耗时数分钟——评估任务整批失败，
# 排查方向还会被误导成"RAG 效果差"。
#
# 预算只作用于「喂给指标的那份副本」，不动库里存的原始 contexts，
# 并统计被裁掉的量回写进 EvalResult.details，让报告里能说清
# "这条分数是在证据被截断的前提下算出来的"。
from typing import Any, Dict, List, Optional, Tuple

# 单条 context 保留的头部长字符数。取头部而不是中部：整页文本的标题、
# 来源、导语都在开头，截尾丢的多是正文细节，截头会把页面识别信息整段丢掉。
DEFAULT_PER_CHUNK_CHARS = 3000

# 一条样本所有 contexts 的总字符预算（约 1.5~2 万 token 的中文/英文混合量级，
# 留出 answer/question/prompt 模板的余量给常见 32k 上下文模型）。
DEFAULT_TOTAL_CHARS = 20000


def apply_context_budget(
    contexts: Optional[List[Any]],
    per_chunk_chars: int = DEFAULT_PER_CHUNK_CHARS,
    total_chars: int = DEFAULT_TOTAL_CHARS,
) -> Tuple[List[str], Optional[Dict[str, Any]]]:
    """按预算裁剪 contexts。

    返回 (裁剪后的 contexts, 统计信息)。未发生裁剪时统计信息为 None，
    调用方可以据此决定要不要往 details 里写截断标记。
    """
    items = [str(c) if c is not None else "" for c in (contexts or [])]
    if not items:
        return [], None

    budget_applied = False
    used = 0
    truncated_chunks = 0
    dropped_chunks = 0
    out: List[str] = []

    for text in items:
        if used >= total_chars:
            dropped_chunks += 1
            budget_applied = True
            continue

        remaining = total_chars - used
        keep = min(per_chunk_chars, remaining)
        piece = text if len(text) <= keep else text[:keep]
        if len(text) > keep:
            truncated_chunks += 1
            budget_applied = True
        out.append(piece)
        used += len(piece)

    if not budget_applied:
        return items, None

    return out, {
        "context_budget_applied": True,
        "context_chunks_original": len(items),
        "context_chunks_used": len(out),
        "context_chunks_dropped": dropped_chunks,
        "context_chunks_truncated": truncated_chunks,
        "context_chars_original": sum(len(t) for t in items),
        "context_chars_used": used,
        "context_per_chunk_chars": per_chunk_chars,
        "context_total_chars": total_chars,
    }
