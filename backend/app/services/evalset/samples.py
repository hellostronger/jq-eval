# 内置评测集样例：离线可导入，作为「任意开源评测集」能力不可达时的兜底，
# 也是开箱即用的演示数据源。格式对齐各评测集真实 schema，见 build_samples.py。
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "evalset_samples"

# model_type 决定归一化分支：llm/embedding/reranker/retrieval
SAMPLE_FILES: Dict[str, Dict[str, Any]] = {
    "ceval_middle_school_mathematics": {
        "file": "ceval_middle_school_mathematics.jsonl",
        "repo": "ceval/ceval-exam", "model_type": "llm",
        "title": "C-Eval 中文多学科选择题",
        "format": "mc", "tags": ["中文", "多学科", "选择题", "同级列A/B/C/D"],
    },
    "mmlu_abstract_algebra": {
        "file": "mmlu_abstract_algebra.jsonl",
        "repo": "cais/mmlu", "model_type": "llm",
        "title": "MMLU 英文多学科选择题",
        "format": "mc", "tags": ["英文", "多学科", "索引答案"],
    },
    "gsm8k": {
        "file": "gsm8k.jsonl",
        "repo": "openai/gsm8k", "model_type": "llm",
        "title": "GSM8K 数学推理生成题",
        "format": "generate", "tags": ["英文", "数学", "生成题", "####数值答案"],
    },
    "stsb_cn": {
        "file": "stsb_cn.jsonl",
        "repo": "mteb/stsbenchmark-sts", "model_type": "embedding",
        "title": "STS-B 中文句对语义相似度",
        "format": "pair_similarity", "tags": ["中文", "句对相似度", "回归打分"],
    },
    "miracl_retrieval": {
        "file": "miracl_retrieval.jsonl",
        "repo": "miracl/miracl", "model_type": "embedding",
        "title": "MIRACL 式检索评测集",
        "format": "retrieval", "tags": ["中文", "检索", "正负例"],
    },
    "passage_relevance": {
        "file": "passage_relevance.jsonl",
        "repo": "castorini/msmarco", "model_type": "reranker",
        "title": "Passage 相关性打分（重排评测）",
        "format": "rerank", "tags": ["中文", "重排", "分级相关度"],
    },
}


def list_samples() -> List[Dict[str, Any]]:
    """内置样例目录（离线可读，标注是否文件实际存在）。"""
    items = []
    for key, meta in SAMPLE_FILES.items():
        path = SAMPLES_DIR / meta["file"]
        rows = 0
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    rows = sum(1 for line in f if line.strip())
            except OSError as exc:
                logger.warning(f"读取样例 {key} 行数失败: {exc}")
        items.append({
            "key": key,
            "title": meta["title"],
            "repo": meta["repo"],
            "model_type": meta["model_type"],
            "format": meta["format"],
            "tags": meta["tags"],
            "rows": rows,
            "available": path.exists(),
        })
    return items


def load_sample(key: str, limit: int = None) -> List[Dict[str, Any]]:
    """加载内置样例原始记录（未归一化）。跳过无法解析的行。"""
    meta = SAMPLE_FILES.get(key)
    if not meta:
        raise KeyError(key)
    path = SAMPLES_DIR / meta["file"]
    if not path.exists():
        raise FileNotFoundError(f"样例文件不存在：{meta['file']}")

    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if limit and len(records) >= limit:
                break
    return records


def get_meta(key: str) -> Dict[str, Any]:
    meta = SAMPLE_FILES.get(key)
    if not meta:
        raise KeyError(key)
    return meta