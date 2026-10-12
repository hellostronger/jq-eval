# UltraData 数据源接入
#
# 目录：https://ultradata.openbmb.cn/datasets 背后是
#   POST https://ultradata.openbmb.cn/api/dataset/list  body {"language":"zh"}
# 返回的每条记录里 md 字段是数据集元数据，但并不总是合法 JSON——历史数据是
# JS 对象字面量（单引号、裸键名、尾逗号），必须容错解析。
#
# 示例数据：backend/app/data/ultradata_samples/*.jsonl 是从各数据集真实抓取的
# 样本（保留原始字段），离线即可导入项目完成画像闭环。
import json
import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

ULTRADATA_LIST_URL = "https://ultradata.openbmb.cn/api/dataset/list"
ULTRADATA_BASE_URL = "https://ultradata.openbmb.cn"
SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "ultradata_samples"

# 本地样例清单：文件名 -> 展示信息（与抓取脚本保持一致）
SAMPLE_FILES: Dict[str, Dict[str, Any]] = {
    "ultrainteract_sft": {
        "file": "ultrainteract_sft.jsonl", "repo": "openbmb/UltraInteract_sft",
        "format": "sft", "level": "L3", "title": "UltraInteract SFT",
        "tags": ["SFT", "复杂推理", "英文"],
    },
    "ultrachat": {
        "file": "ultrachat.jsonl", "repo": "openbmb/UltraChat",
        "format": "chat", "level": "L3", "title": "UltraChat",
        "tags": ["多轮交互", "SFT", "英文"],
    },
    "ultrafeedback": {
        "file": "ultrafeedback.jsonl", "repo": "openbmb/UltraFeedback",
        "format": "preference", "level": "L3", "title": "UltraFeedback",
        "tags": ["偏好学习", "奖励模型", "英文"],
    },
    "sft_agent_2609": {
        "file": "sft_agent_2609.jsonl", "repo": "openbmb/UltraData-SFT-Agent-2609",
        "format": "agent", "level": "L3", "title": "UltraData-SFT-Agent-2609",
        "tags": ["Agent", "工具调用", "SFT"],
    },
    "ultrafineweb": {
        "file": "ultrafineweb.jsonl", "repo": "openbmb/Ultra-FineWeb",
        "format": "pretrain", "level": "L2", "title": "Ultra-FineWeb",
        "tags": ["预训练", "网页语料", "数据过滤"],
    },
    "ultrafineweb_l3": {
        "file": "ultrafineweb_l3.jsonl", "repo": "openbmb/Ultra-FineWeb-L3",
        "format": "pretrain", "level": "L3", "title": "Ultra-FineWeb-L3",
        "tags": ["数据合成", "问答生成", "知识增强"],
    },
    "ultrafineweb_l1": {
        "file": "ultrafineweb_l1.jsonl", "repo": "openbmb/Ultra-FineWeb-L1",
        "format": "pretrain", "level": "L1", "title": "Ultra-FineWeb-L1",
        "tags": ["预训练", "网页语料", "去重"],
    },
    "ultradata_math": {
        "file": "ultradata_math.jsonl", "repo": "openbmb/UltraData-Math",
        "format": "pretrain", "level": "L1", "title": "UltraData-Math",
        "tags": ["数学推理", "数据清洗", "预训练"],
    },
    "ultrax_preview": {
        "file": "ultrax_preview.jsonl", "repo": "openbmb/UltraX-Preview",
        "format": "pretrain", "level": "L1", "title": "UltraX-Preview",
        "tags": ["数据精炼", "预训练", "函数调用"],
    },
    "dcad_2000": {
        "file": "dcad_2000.jsonl", "repo": "openbmb/DCAD-2000",
        "format": "pretrain", "level": "L1", "title": "DCAD-2000",
        "tags": ["预训练", "网页语料", "多语言"],
    },
}

_BARE_KEY_RE = re.compile(r"(?m)(?<=[{,\n])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:")
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def parse_dataset_md(md: Any) -> Dict[str, Any]:
    """解析 UltraData 的 md 字段（JSON / JS 对象字面量双兼容）"""
    if isinstance(md, dict):
        return md
    if not isinstance(md, str) or not md.strip():
        return {}
    text = md.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        # 裸键补引号后交给字面量解析：单引号字符串、true/false/null 都能吃下，
        # 比全局替换单引号安全（不会破坏 don't 这类撇号）
        quoted = _BARE_KEY_RE.sub(r'"\1":', text)
        quoted = _TRAILING_COMMA_RE.sub(r"\1", quoted)
        parsed = ast.literal_eval(quoted)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, SyntaxError):
        return {}


def _absolute(md_path: Optional[str]) -> Optional[str]:
    if not md_path:
        return None
    if md_path.startswith("http"):
        return md_path
    return ULTRADATA_BASE_URL + (md_path if md_path.startswith("/") else "/" + md_path)


def normalize_catalog_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """目录条目 + md 元数据 → 前端可直接渲染的结构"""
    meta = parse_dataset_md(item.get("md"))
    links = meta.get("links") if isinstance(meta.get("links"), dict) else {}
    extra = meta.get("extraInfo") if isinstance(meta.get("extraInfo"), dict) else {}
    org = meta.get("organization") if isinstance(meta.get("organization"), dict) else {}
    return {
        "source_id": item.get("id"),
        "name": meta.get("name") or item.get("name"),
        "level": meta.get("level"),
        "description": (meta.get("description") or meta.get("summary") or "")[:2000],
        "tags": meta.get("tags") or [],
        "tags_en": meta.get("tagsEn") or [],
        "date": meta.get("dateZh") or meta.get("date"),
        "documents": meta.get("documents") or meta.get("documentsEn"),
        "token": meta.get("token"),
        "size": meta.get("size"),
        "license": meta.get("license"),
        "downloads": meta.get("downloads"),
        "organization": org.get("name") or "OpenBMB",
        "languages": extra.get("languagesZh") or extra.get("languages") or [],
        "tasks": extra.get("tasksZh") or extra.get("tasks") or [],
        "modalities": extra.get("modalitiesZh") or extra.get("modalities") or [],
        "links": {k: v for k, v in links.items() if v},
        "readme_url": _absolute(meta.get("mdPathZh") or meta.get("mdPath")),
        "is_coming": bool(meta.get("isComing")),
        "raw": meta,
    }


async def fetch_catalog(language: str = "zh", timeout: float = 20.0) -> List[Dict[str, Any]]:
    """拉取 UltraData 数据集目录（失败抛给调用方决定兜底）"""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.post(
            ULTRADATA_LIST_URL,
            json={"language": language},
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        body = resp.json()
    items = body.get("data") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return []
    return [normalize_catalog_item(item) for item in items if isinstance(item, dict)]


def list_samples() -> List[Dict[str, Any]]:
    """本地样例清单（带文件是否存在与行数）"""
    out = []
    for key, meta in SAMPLE_FILES.items():
        path = SAMPLES_DIR / meta["file"]
        exists = path.exists()
        rows = 0
        if exists:
            with open(path, "rb") as fh:
                rows = sum(1 for line in fh if line.strip())
        out.append({
            "key": key,
            "title": meta["title"],
            "repo": meta["repo"],
            "format": meta["format"],
            "level": meta["level"],
            "tags": meta["tags"],
            "rows": rows,
            "available": exists and rows > 0,
        })
    return out


def load_sample(key: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """读取本地样例记录（原始字段，不做归一化）"""
    meta = SAMPLE_FILES.get(key)
    if not meta:
        raise KeyError(f"未知样例: {key}")
    path = SAMPLES_DIR / meta["file"]
    if not path.exists():
        raise FileNotFoundError(f"样例文件不存在: {meta['file']}")
    records: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
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
