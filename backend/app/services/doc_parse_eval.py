# 解析结果质量评估
# 对 minerU 等解析服务产出的 Markdown 做结构化指标打分（0-100），可选 LLM 深度评估
import re
from typing import Any, Dict, List, Optional


def evaluate_result(file_name: str, md_content: str, duration: Optional[float] = None) -> Dict[str, Any]:
    """评估单个解析结果质量

    指标（各 0-1 权重加权合成为 0-100 总分）：
    - content_yield: 内容产出量（相对常见文档规模的启发式）
    - structure: 标题/列表等结构保留
    - readability: 乱码与噪声控制
    - completeness: 是否被截断/为空
    """
    text = md_content or ""
    length = len(text.strip())

    # 1. 内容产出量：有效字符数（去掉空白）映射到 0-1，5k 字以上视为满产
    effective_chars = len(re.sub(r"\s", "", text))
    content_yield = min(effective_chars / 5000, 1.0) if effective_chars else 0.0

    # 2. 结构保留：标题、列表、表格、图片等 Markdown 元素密度
    headings = len(re.findall(r"^#{1,6}\s", text, flags=re.M))
    list_items = len(re.findall(r"^\s*[-*+\d]+[.)]?\s", text, flags=re.M))
    tables = len(re.findall(r"\|.*\|", text))
    images = len(re.findall(r"!\[[^\]]*\]\([^)]*\)", text))
    structure_score = (
        min(headings / 5, 1.0) * 0.4
        + min(list_items / 10, 1.0) * 0.3
        + min(tables / 5, 1.0) * 0.2
        + min(images / 2, 1.0) * 0.1
    )

    # 3. 可读性：乱码字符（替换符/控制符）与超长无空格行占比
    bad_chars = sum(text.count(c) for c in ("�", "\x00"))
    lines = [ln for ln in text.splitlines() if ln.strip()]
    long_lines = sum(1 for ln in lines if len(ln) > 500)
    long_ratio = long_lines / len(lines) if lines else 0.0
    readability = max(0.0, 1.0 - bad_chars / 50 - long_ratio * 0.5) if lines else 0.0

    # 4. 完整性：非空且没有明显截断标记
    truncated = bool(re.search(r"(?:\.{3}|…)\s*$", text.strip())) if text.strip() else False
    completeness = 0.0 if length == 0 else (0.8 if truncated else 1.0)

    score = (
        content_yield * 0.35
        + structure_score * 0.25
        + readability * 0.25
        + completeness * 0.15
    ) * 100

    suggestions: List[str] = []
    if content_yield < 0.2:
        suggestions.append("解析产出内容过少，请检查源文件是否为扫描件并确认 OCR 已开启")
    if headings == 0 and length > 1000:
        suggestions.append("未识别出任何标题结构，可尝试更换解析后端（如 vlm）")
    if bad_chars > 10:
        suggestions.append(f"检测到 {bad_chars} 处乱码字符，可能存在编码或识别问题")
    if truncated:
        suggestions.append("解析结果疑似被截断")
    if not suggestions:
        suggestions.append("解析质量良好")

    return {
        "score": round(score, 1),
        "metrics": {
            "content_yield": round(content_yield, 3),
            "structure": round(structure_score, 3),
            "readability": round(readability, 3),
            "completeness": round(completeness, 3),
        },
        "stats": {
            "effective_chars": effective_chars,
            "headings": headings,
            "list_items": list_items,
            "table_rows": tables,
            "images": images,
            "duration": duration,
        },
        "suggestions": suggestions,
    }


def compute_batch_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """汇总批次评估结果"""
    scores = [it["evaluation"]["score"] for it in items if it.get("evaluation")]
    if not scores:
        return {}
    return {
        "total": len(scores),
        "avg_score": round(sum(scores) / len(scores), 1),
        "max_score": round(max(scores), 1),
        "min_score": round(min(scores), 1),
        "good_count": sum(1 for s in scores if s >= 80),
        "poor_count": sum(1 for s in scores if s < 60),
        "files": [
            {"file_name": it.get("file_name"), "score": it["evaluation"]["score"]}
            for it in items if it.get("evaluation")
        ],
    }
