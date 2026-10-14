# 评测集归一化
#
# 与 training_data/normalize.py 对称，但判定对象完全不同：
# 训练数据问「这条样本长什么样」，评测集问「这条样本怎么判分」。
# 因此归一化以 model_type 分派，识别四种评测形态：
#   llm       question → choices/answer          答题正确率
#   embedding query ↔ positive/negative passages  向量检索排序质量
#   reranker  (query, passages[]) → relevance     重排质量
#   retrieval query → gold 上下文/分片 id          RAG 检索评测
#
# 设计约束：未知字段全部保留在 payload，保证「任意开源评测集」不丢信息。
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Dict, List, Optional

# 复用训练数据画像的公共工具，避免两套口径漂移
from ..training_data.normalize import (  # noqa: F401  (部分导出供调用方直接使用)
    _first,
    _parse_jsonish,
    _s,
    detect_language,
    estimate_tokens,
)

# ---------------------------------------------------------------------------
# 评测集归属
# ---------------------------------------------------------------------------
MODEL_LLM = "llm"
MODEL_EMBEDDING = "embedding"
MODEL_RERANKER = "reranker"
MODEL_RETRIEVAL = "retrieval"

MODEL_TYPES = [MODEL_LLM, MODEL_EMBEDDING, MODEL_RERANKER, MODEL_RETRIEVAL]

MODEL_LABELS = {
    MODEL_LLM: "大模型",
    MODEL_EMBEDDING: "向量模型",
    MODEL_RERANKER: "重排模型",
    MODEL_RETRIEVAL: "检索/RAG",
}

# ---------------------------------------------------------------------------
# 题型
# ---------------------------------------------------------------------------
FORMAT_MC = "mc"                        # 选择题（单选/多选）
FORMAT_GENERATE = "generate"            # 开放生成
FORMAT_JUDGE = "judge"                  # 判别/是非
FORMAT_PAIR_SIMILARITY = "pair_similarity"  # 句对相似度（STS 类）
FORMAT_RETRIEVAL = "retrieval"          # 检索：query → gold 上下文
FORMAT_RERANK = "rerank"                # 重排：候选段落打分
FORMAT_AGENTIC = "agentic"              # 多轮/工具轨迹
FORMAT_OTHER = "other"

FORMAT_LABELS = {
    FORMAT_MC: "选择题",
    FORMAT_GENERATE: "生成题",
    FORMAT_JUDGE: "判别题",
    FORMAT_PAIR_SIMILARITY: "句对相似度",
    FORMAT_RETRIEVAL: "检索题",
    FORMAT_RERANK: "重排题",
    FORMAT_AGENTIC: "Agent 轨迹",
    FORMAT_OTHER: "其他",
}

ANSWER_SINGLE = "single_choice"
ANSWER_MULTI = "multi_choice"
ANSWER_FREE = "free_text"
ANSWER_NUMERIC = "numeric"
ANSWER_RELEVANCE = "relevance"
ANSWER_NONE = "none"

ANSWER_LABELS = {
    ANSWER_SINGLE: "单选",
    ANSWER_MULTI: "多选",
    ANSWER_FREE: "自由文本",
    ANSWER_NUMERIC: "数值",
    ANSWER_RELEVANCE: "相关度",
    ANSWER_NONE: "无标准答案",
}

# 选项标签：ABCDEFGH（评测集极少超过 8 个选项）
CHOICE_LABELS = list("ABCDEFGH")

# ---------------------------------------------------------------------------
# 字段别名 —— 覆盖主流开源评测集的列命名差异
# ---------------------------------------------------------------------------
QUESTION_KEYS = (
    "question", "query", "prompt", "instruction", "input", "problem", "stem",
)
ANSWER_KEYS = (
    "answer", "answerKey", "answer_key", "label", "target", "gold", "gold_answer",
    "correct_answer", "correctAnswer", "output", "solution", "final_answer",
)
CHOICE_KEYS = (
    "choices", "options", "candidates", "answers_options", "distractors",
    "choice_list", "选项", "answer_options",
)
# 部分评测集（CEval/CMMLU 等）把选项铺成同级列 A/B/C/D，需单独识别
CHOICE_SIBLING_KEYS = ("A", "B", "C", "D", "E", "F", "G", "H")
CONTEXT_KEYS = (
    "contexts", "context", "gold_contexts", "paragraph", "passage", "document",
    "reference", "background",
)
POSITIVE_KEYS = (
    "positive", "positive_passages", "positives", "positive_texts",
    "relevant_passages", "gold_passages", "pos",
)
NEGATIVE_KEYS = (
    "negative", "negative_passages", "negatives", "negative_texts",
    "hard_negatives", "neg",
)
PASSAGE_KEYS = ("passages", "candidates_passages", "docs", "documents", "contexts_list")
SUBJECT_KEYS = (
    "subject", "discipline", "category", "topic", "domain", "field", "knowledge_point",
    "学科", "类别",
)
DIFFICULTY_KEYS = ("difficulty", "level", "grade", "hardness", "难度", "级别")
SPLIT_KEYS = ("split", "subset", "subset_name", "partition")

# 题干归一化后取这些键认为命中（用于指纹对比的健壮性）
_KNOWN_KEYS = set(
    QUESTION_KEYS + ANSWER_KEYS + CHOICE_KEYS + CONTEXT_KEYS + POSITIVE_KEYS
    + NEGATIVE_KEYS + PASSAGE_KEYS + SUBJECT_KEYS + DIFFICULTY_KEYS + SPLIT_KEYS
    + ("explanation", "rationale", "analysis", "解析", "id", "_id", "qid", "index")
)


# ---------------------------------------------------------------------------
# 题干指纹：跨评测集去重与污染检测的唯一依据
# ---------------------------------------------------------------------------
def normalize_for_hash(text: str) -> str:
    """题干归一化指纹的预处理。

    跨集比对必须抹平「排版差异」但保留「语义」：
      NFKC 统一全角/半角 → 转小写 → 去所有空白 → 去标点（ASCII + CJK）
    这样 C-Eval 的「下列说法正确的是（ ）」与 CMMLU 的「下列说法正确的是」能撞上，
    而不同题干不会因标点差异被误判为同一题。
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = t.lower()
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[^\w\u4e00-\u9fff]+", "", t)
    return t


def question_hash(question: str) -> str:
    """仅题干的指纹：用于跨评测集重复/污染检测。"""
    norm = normalize_for_hash(question)
    if not norm:
        return ""
    return hashlib.sha1(norm.encode("utf-8", "ignore")).hexdigest()


def qa_hash(question: str, answer: str) -> str:
    """题干 + 答案的指纹：用于集内精确去重与答案冲突检测。"""
    norm = normalize_for_hash(question)
    if not norm:
        return ""
    ans = normalize_for_hash(answer or "")
    return hashlib.sha1((norm + "\x00" + ans).encode("utf-8", "ignore")).hexdigest()


# ---------------------------------------------------------------------------
# 选项归一化
# ---------------------------------------------------------------------------
def _extract_choices(record: Dict[str, Any]) -> List[str]:
    """取出选项列表，兼容三种常见写法。

    1. 列表/字典：choices / options / [{"label","text"}] / {"A": "..."}
    2. 字符串拆分："A)xx B)yy"
    3. 同级列（CEval/CMMLU 真实形态）：{"question":..., "A":"...", "B":"...", "answer":"B"}
       这种最容易漏，若不识别会把选择题误判成判别题并丢掉全部选项
    """
    raw = _first(record, *CHOICE_KEYS)
    if raw is None:
        # 兜底：识别 A/B/C/D 同级列
        siblings: List[str] = []
        for label in CHOICE_SIBLING_KEYS:
            val = record.get(label)
            text = _s(val).strip()
            if text and text not in ("", "N/A"):
                siblings.append(text)
            elif val is not None:
                break  # 选项列应连续，遇到空洞即认为不是同级列形态
        return siblings if len(siblings) >= 2 else []
    raw = _parse_jsonish(raw)
    if isinstance(raw, dict):
        # {"A": "...", "B": "..."} 形态
        ordered = [raw[k] for k in sorted(raw.keys()) if _s(raw[k]).strip()]
        return [_s(v).strip() for v in ordered if _s(v).strip()]
    if isinstance(raw, (list, tuple)):
        out: List[str] = []
        for item in raw:
            if isinstance(item, dict):
                # [{"label": "A", "text": "..."}] 形态
                text = _first(item, "text", "content", "value", "option", "answer", "label")
                out.append(_s(text).strip())
            else:
                out.append(_s(item).strip())
        return [c for c in out if c]
    text = _s(raw).strip()
    if not text:
        return []
    # 少数集把选项写成一个 "A)xx B)yy" 的串
    parts = re.split(r"(?=(?:^|\s)[A-H][).:、])", text)
    if len(parts) > 1:
        cleaned = [re.sub(r"^\s*[A-H][).:、]\s*", "", p).strip() for p in parts]
        cleaned = [c for c in cleaned if c]
        if len(cleaned) >= 2:
            return cleaned
    return [text]


def _labels_from_scalar(value: Any, choices: List[str]) -> List[str]:
    """从单个标量答案值解析出选项标签（索引式/标签式/文本式）。"""
    if value is None:
        return []
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        idx = int(value)
        return [CHOICE_LABELS[idx]] if 0 <= idx < len(choices) else []
    text = _s(value).strip()
    if not text:
        return []
    if choices:
        for i, c in enumerate(choices):
            if normalize_for_hash(text) == normalize_for_hash(c):
                return [CHOICE_LABELS[i]]
    cleaned = re.sub(r"[()\[\]{}.、,，\s]", "", text).upper()
    if cleaned and all(ch in CHOICE_LABELS for ch in cleaned):
        return list(dict.fromkeys(cleaned))
    return []


def _extract_answer_labels(record: Dict[str, Any], choices: List[str]) -> List[str]:
    """抽取正确项标签。

    覆盖三种常见写法：
      "B" / ["B"]           标签式
      2 / 1                  索引式（0-based）
      选项文本本身            文本式
    """
    raw = _first(record, *ANSWER_KEYS)
    if raw is None:
        return []
    raw = _parse_jsonish(raw)
    if isinstance(raw, (list, tuple)):
        # 多选：逐项按标量路径解析。注意不能用 {"_": item} 递归，
        # "_" 不在 ANSWER_KEYS 里，_first 恒返回 None（实测踩过）
        labels: List[str] = []
        for item in raw:
            labels.extend(_labels_from_scalar(item, choices))
        return list(dict.fromkeys(labels))
    # 标量路径（标签式/索引式/文本式统一入口）
    return _labels_from_scalar(raw, choices)


def _classify_answer_type(answer_labels: List[str], choices: List[str]) -> str:
    if not choices:
        return ANSWER_NONE
    if not answer_labels:
        return ANSWER_NONE
    return ANSWER_MULTI if len(answer_labels) > 1 else ANSWER_SINGLE


# ---------------------------------------------------------------------------
# embedding / reranker 专有字段
# ---------------------------------------------------------------------------
def _extract_texts(value: Any) -> List[str]:
    """把多种嵌套形态的段落列表压成纯文本列表。"""
    if value is None:
        return []
    value = _parse_jsonish(value)
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        text = _first(value, "text", "content", "passage", "document", "body", "value")
        return [_s(text).strip()] if _s(text).strip() else []
    if isinstance(value, (list, tuple)):
        out: List[str] = []
        for item in value:
            out.extend(_extract_texts(item))
        return [t for t in out if t]
    text = _s(value).strip()
    return [text] if text else []


def _extract_id_references(record: Dict[str, Any], *keys: str) -> List[str]:
    """抽取 id 引用式正/负例（BEIR 形态：正例在独立 corpus 里，本表只存 id）。"""
    raw = _first(record, *keys)
    if raw is None:
        return []
    raw = _parse_jsonish(raw)
    if isinstance(raw, (list, tuple)):
        return [_s(v).strip() for v in raw if _s(v).strip()]
    text = _s(raw).strip()
    return [text] if text else []


def _extract_passages(record: Dict[str, Any]) -> tuple:
    """抽取重排候选段落与相关度标签。

    支持两种形态：
      passages: ["文本A", "文本B"]                  → relevance=[]
      passages: [{"text": "...", "relevance": 1}] → relevance=["1","0"]
      candidates: {"pos": [...], "neg": [...]}     → 由正/负例兜底
    """
    raw = _first(record, *PASSAGE_KEYS)
    raw = _parse_jsonish(raw)
    texts: List[str] = []
    labels: List[str] = []
    if isinstance(raw, (list, tuple)) and raw:
        for item in raw:
            if isinstance(item, dict):
                text = _first(item, "text", "content", "passage", "document", "body", "chunk")
                texts.append(_s(text).strip())
                rel = _first(item, "relevance", "label", "relevance_label", "score", "grade", "is_relevant")
                labels.append(_s(rel).strip() if rel is not None else "")
            else:
                texts.append(_s(item).strip())
                labels.append("")
    if not texts:
        texts = _extract_texts(_first(record, *POSITIVE_KEYS))
        labels = ["1"] * len(texts)
    return texts, labels


# ---------------------------------------------------------------------------
# 题型判定
# ---------------------------------------------------------------------------
def detect_task_format(
    record: Dict[str, Any],
    choices: List[str],
    model_type: str,
    positives: List[str],
    negatives: List[str],
    passages: List[str],
) -> str:
    """按 model_type 分派判定题型，命中即停。"""
    keys = {k.lower() for k in record}
    has_answer = any(k in keys for k in {a.lower() for a in ANSWER_KEYS})

    if model_type == MODEL_EMBEDDING:
        # 句对相似度：两个句子 + 连续相似度分（STS 类）
        if ("sentence1" in keys and "sentence2" in keys) or (
            {"src", "tgt"} & keys and has_answer
        ):
            return FORMAT_PAIR_SIMILARITY
        if positives or negatives:
            return FORMAT_RETRIEVAL
        # 仍要识别出选择题，否则 embedding 集里混入的答题数据
        # 会被归成 other，导致画像的归属体检抓不到「归类错误」
        if choices and len(choices) >= 2:
            return FORMAT_MC
        return FORMAT_OTHER

    if model_type == MODEL_RERANKER:
        if passages or positives or negatives:
            return FORMAT_RERANK
        return FORMAT_OTHER

    if model_type == MODEL_RETRIEVAL:
        if (
            record.get("target_chunk_ids") or record.get("gold_chunk_ids")
            or record.get("positive_chunk_ids")
        ):
            return FORMAT_RETRIEVAL
        if positives:
            return FORMAT_RETRIEVAL
        if choices:
            return FORMAT_MC
        return FORMAT_GENERATE if has_answer else FORMAT_OTHER

    # ---- llm ----
    if choices and len(choices) >= 2:
        return FORMAT_MC
    # 代码/函数签名类（HumanEval：prompt 是函数头，canonical_solution/test 不是答案字段）
    if keys & {"canonical_solution", "entry_point", "test_setup", "test_list"}:
        return FORMAT_GENERATE
    if keys & {"messages", "conversation", "conversations"} or record.get("tools"):
        return FORMAT_AGENTIC
    text = _s(record.get("answer")) if "answer" in record else ""
    if has_answer and len(text.strip()) > 20:
        return FORMAT_GENERATE
    if has_answer:
        return FORMAT_JUDGE
    return FORMAT_OTHER


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def normalize_record(
    record: Dict[str, Any],
    seq: int = 0,
    model_type: str = MODEL_LLM,
) -> Dict[str, Any]:
    """把任意评测集的一条原始记录归一化成 eval_set_records 的列。"""
    if not isinstance(record, dict):
        record = {"text": _s(record)}

    # 题面
    question = _s(_first(record, *QUESTION_KEYS)).strip()

    # 选项与答案
    choices = _extract_choices(record)
    answer_labels = _extract_answer_labels(record, choices)
    choice_labels = CHOICE_LABELS[: len(choices)]
    answer_type = _classify_answer_type(answer_labels, choices)

    # 生成题/判别题的参考答案。选择题的答案已在 answer_labels 里，
    # 此处必须留空——否则会把 "B" 这种标签写进 answer_text，污染答案长度画像
    if choices:
        answer_text = ""
    else:
        raw_answer = _first(record, *ANSWER_KEYS)
        answer_text = _s(raw_answer).strip()
        # GSM8K 形态："...#### 8" → 只保留最终答案，去掉推理尾巴
        m = re.search(r"####\s*(.+)$", answer_text)
        if m:
            answer_text = m.group(1).strip()

    # 上下文 / gold
    contexts = _extract_texts(_first(record, *CONTEXT_KEYS))

    # embedding / reranker
    positives = _extract_texts(_first(record, *POSITIVE_KEYS))
    negatives = _extract_texts(_first(record, *NEGATIVE_KEYS))
    # BEIR 形态：正例以 id 引用独立 corpus，无内联文本，按 id 记数即可
    if not positives:
        pos_ids = _extract_id_references(record, "positive_ids", "positive_id", "pos_ids")
        if pos_ids:
            positives = list(pos_ids)
    if not negatives:
        neg_ids = _extract_id_references(record, "negative_ids", "negative_id", "neg_ids")
        if neg_ids:
            negatives = list(neg_ids)

    # passages 抽取放在正/负例之后：_extract_passages 的内部兜底只认 positives，
    # 若先调用会拿到仅含正例的 passages，后续 negatives 就被吞掉（实测踩过）
    passages, relevance = _extract_passages(record)
    # _extract_passages 的内部兜底只用 positives，会在存在负例时提前返回正例子集。
    # 因此只要记录里有 negatives 却没被计入 passages/relevance，就必须用
    # 正+负 重建，否则重排集的相关度标签与候选段落数都会偏小（实测踩过）
    if negatives and len(passages) < len(positives) + len(negatives):
        passages = positives + negatives
        relevance = ["1"] * len(positives) + ["0"] * len(negatives)
    elif not passages and (positives or negatives):
        passages = positives + negatives
        relevance = ["1"] * len(positives) + ["0"] * len(negatives)
    if not contexts and positives:
        contexts = positives

    task_format = detect_task_format(
        record, choices, model_type, positives, negatives, passages
    )

    # 能力维度
    subject = _s(_first(record, *SUBJECT_KEYS)).strip()[:100] or None
    category = _s(record.get("task") or record.get("task_type") or record.get("type")).strip()[:100] or None
    difficulty = _s(_first(record, *DIFFICULTY_KEYS)).strip()[:20] or None
    split = _s(_first(record, *SPLIT_KEYS)).strip()[:20] or None
    explanation = _s(_first(record, "explanation", "rationale", "analysis", "解析")).strip() or None

    # 长度
    question_length = len(question)
    ctx_texts = contexts or passages
    context_length = sum(len(t) for t in ctx_texts)
    full_text = question + "".join(ctx_texts) + answer_text + "".join(choices)
    est_tokens = estimate_tokens(full_text)

    # 溯源：payload 里挑出值得留档的元信息
    metadata = {}
    for key in ("id", "_id", "qid", "idx", "index", "repo", "revision", "license",
                "dataset", "config", "version", "seed", "task_name", "source"):
        if key in record and not isinstance(record[key], (dict, list)):
            value = _s(record[key]).strip()
            if value and len(value) <= 200:
                metadata[key] = value
    for key in ("license", "repo", "revision", "language", "lang"):
        if key not in metadata and record.get(key):
            metadata[key] = _s(record[key]).strip()[:200]

    answer_for_hash = "".join(answer_labels) or answer_text

    return {
        "seq": seq,
        "model_type": model_type,
        "task_format": task_format,
        "answer_type": answer_type,
        "question": question or None,
        "contexts": contexts,
        "target_chunk_ids": [],
        "choices": choices,
        "choice_labels": choice_labels,
        "answer_labels": answer_labels,
        "answer_text": answer_text or None,
        "explanation": explanation,
        "positive_texts": positives,
        "negative_texts": negatives,
        "passages": passages,
        "relevance_labels": relevance,
        "pos_count": len(positives),
        "neg_count": len(negatives),
        "subject": subject,
        "category": category,
        "difficulty": difficulty,
        "language": detect_language(question or full_text),
        "split": split,
        "question_length": question_length,
        "context_length": context_length,
        "est_tokens": est_tokens,
        "question_hash": question_hash(question) or None,
        "qa_hash": qa_hash(question, answer_for_hash) or None,
        "payload": record,
        "record_metadata": metadata,
    }


def normalize_batch(
    records: List[Dict[str, Any]], model_type: str = MODEL_LLM
) -> List[Dict[str, Any]]:
    return [normalize_record(r, seq=i, model_type=model_type) for i, r in enumerate(records)]