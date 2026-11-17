# 多模态嵌入评测：数据导入解析
#
# 支持三类输入，统一归一化为 (query, candidate, label) 对：
#   1. MMEB 官方 jsonl（扁平对）：qry/qry_image_path + tgt/tgt_image_path + label
#   2. MMEB 的 pos/neg 写法：pos_text/pos_image_path + hard_neg_text/hard_neg_image_path
#   3. 通用分组格式：{"query_id":..., "query": {...}, "candidates":[{...}, ...]}
# 图片引用可以是 zip 内相对路径、http(s) URL 或 data URI；落地由 media 模块负责。
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

MAX_MANIFEST_BYTES = 100 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED = 2 * 1024 * 1024 * 1024
MAX_SAMPLES = 200_000
MAX_REPORTED_ERRORS = 5

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

_QUERY_TEXT_KEYS = (
    "qry_text", "query_text", "question", "qry", "query", "query_instruction",
)
_QUERY_IMAGE_KEYS = (
    "qry_image_path", "query_image_path", "qry_image", "query_image",
    "query_image_url", "qry_image_url",
)
_TARGET_TEXT_KEYS = (
    "tgt_text", "target_text", "answer", "tgt", "target",
)
_TARGET_IMAGE_KEYS = (
    "tgt_image_path", "target_image_path", "tgt_image", "target_image",
    "pos_image_path", "pos_image", "target_image_url", "tgt_image_url",
)
_POS_TEXT_KEYS = ("pos_text", "positive_text")
_POS_IMAGE_KEYS = ("pos_image_path", "pos_image", "positive_image_path")
_NEG_TEXT_KEYS = ("neg_text", "hard_neg_text", "negative_text", "hard_negative_text")
_NEG_IMAGE_KEYS = ("neg_image_path", "neg_image", "hard_neg_image_path", "hard_negative_image_path")
_LABEL_KEYS = ("label", "relevance", "rel", "is_positive", "match")
_QID_KEYS = ("qid", "query_id", "group_id")
_SUBSET_KEYS = ("subset", "task", "task_type", "category", "source")


@dataclass
class RawSample:
    qid: str
    subset: Optional[str]
    query_text: Optional[str]
    query_image_ref: Optional[str]
    target_text: Optional[str]
    target_image_ref: Optional[str]
    label: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedFile:
    samples: List[RawSample]
    images: Dict[str, bytes]  # zip 内图片：归一化相对路径 -> 内容
    image_names: Dict[str, str]  # basename -> 路径（仅唯一时）
    source_meta: Dict[str, Any]


def parse_dataset_file(filename: str, raw: bytes) -> ParsedFile:
    """按扩展名分派解析；失败抛 ValueError（路由层转 400）"""
    name = (filename or "").lower()
    if name.endswith(".zip"):
        return _parse_zip(raw)
    if name.endswith((".jsonl", ".json")):
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ValueError(f"文件过大（>{MAX_MANIFEST_BYTES // 1024 // 1024}MB）")
        rows = _load_rows(raw, filename)
        samples, stats = _rows_to_samples(rows, default_subset=None)
        return ParsedFile(
            samples=samples,
            images={},
            image_names={},
            source_meta={"file": filename, "format": name.rsplit(".", 1)[-1], **stats},
        )
    raise ValueError("仅支持 .jsonl / .json / .zip（zip 内放 jsonl 与图片目录）")


def _parse_zip(raw: bytes) -> ParsedFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"zip 解析失败：{exc}") from exc

    total_uncompressed = sum(i.file_size for i in zf.infolist())
    if total_uncompressed > MAX_ZIP_UNCOMPRESSED:
        raise ValueError(f"压缩包解压后超过 {MAX_ZIP_UNCOMPRESSED // 1024 // 1024}MB 上限")

    images: Dict[str, bytes] = {}
    manifests: List[Tuple[str, bytes]] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        norm = _safe_zip_path(info.filename)
        lower = norm.lower()
        if lower.endswith((".jsonl", ".json")):
            if info.file_size > MAX_MANIFEST_BYTES:
                raise ValueError(f"{norm} 过大（>{MAX_MANIFEST_BYTES // 1024 // 1024}MB）")
            manifests.append((norm, zf.read(info)))
        elif any(lower.endswith(ext) for ext in IMAGE_EXTS):
            images[norm] = zf.read(info)

    if not manifests:
        raise ValueError("zip 内未找到 .jsonl/.json 清单文件")

    # 多个清单（如 MMEB 每个子任务一个 jsonl）合并；用文件名 stem 兜底 subset
    samples: List[RawSample] = []
    stats_acc = {"unlabeled": 0, "total_rows": 0}
    for norm, data in sorted(manifests):
        rows = _load_rows(data, norm)
        stem = norm.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        part, stats = _rows_to_samples(rows, default_subset=stem or None)
        samples.extend(part)
        for key in stats_acc:
            stats_acc[key] += stats.get(key, 0)
        if len(samples) > MAX_SAMPLES:
            raise ValueError(f"样本数超过 {MAX_SAMPLES} 上限，请拆分数据集")

    basenames: Dict[str, str] = {}
    dup_basenames = set()
    for path in images:
        base = path.rsplit("/", 1)[-1].lower()
        if base in basenames:
            dup_basenames.add(base)
        else:
            basenames[base] = path
    for dup in dup_basenames:
        basenames.pop(dup, None)

    return ParsedFile(
        samples=samples,
        images=images,
        image_names=basenames,
        source_meta={
            "format": "zip",
            "manifests": [m[0] for m in manifests],
            "image_files": len(images),
            **stats_acc,
        },
    )


def _safe_zip_path(name: str) -> str:
    normalized = (name or "").replace("\\", "/").lstrip("/")
    segments = [s for s in normalized.split("/") if s not in ("", ".")]
    if any(s == ".." for s in segments):
        raise ValueError(f"zip 内含非法路径：{name}")
    return "/".join(segments)


def _load_rows(raw: bytes, source: str) -> List[Dict[str, Any]]:
    text = raw.decode("utf-8-sig", errors="replace")
    stripped = text.strip()
    if not stripped:
        return []
    if not stripped.startswith(("{", "[")):
        return _load_jsonl(text, source)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        # 首字符是 { 但整体不是 JSON：多为缺外层数组的 jsonl
        return _load_jsonl(text, source)

    if isinstance(payload, list):
        return _as_dict_rows(payload, source)
    if isinstance(payload, dict):
        for key in ("data", "samples", "records", "items", "test_cases"):
            if isinstance(payload.get(key), list):
                return _as_dict_rows(payload[key], source)
        # 单个字典视为一条记录（单行 jsonl 也会走到这里）
        return [payload]


def _load_jsonl(text: str, source: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"第 {lineno} 行: {exc.msg}")
            if len(errors) >= MAX_REPORTED_ERRORS:
                break
            continue
        if not isinstance(obj, dict):
            errors.append(f"第 {lineno} 行: 不是 JSON 对象")
        else:
            rows.append(obj)
    if errors:
        raise ValueError(f"{source} 解析失败：" + "；".join(errors))
    return rows


def _as_dict_rows(items: List[Any], source: str) -> List[Dict[str, Any]]:
    rows = [item for item in items if isinstance(item, dict)]
    if len(rows) != len(items):
        raise ValueError(f"{source} 含 {len(items) - len(rows)} 条非对象记录")
    return rows


def _rows_to_samples(
    rows: List[Dict[str, Any]], default_subset: Optional[str]
) -> Tuple[List[RawSample], Dict[str, int]]:
    samples: List[RawSample] = []
    unlabeled = 0
    for idx, row in enumerate(rows):
        grouped = _grouped_candidates(row)
        try:
            if grouped is not None:
                samples.extend(
                    _from_grouped(row, grouped, default_subset, idx)
                )
            else:
                part, had_label = _from_pair(row, default_subset, idx)
                samples.extend(part)
                if not had_label:
                    unlabeled += 1
        except ValueError as exc:
            raise ValueError(f"第 {idx + 1} 条记录无效：{exc}") from exc
        if len(samples) > MAX_SAMPLES:
            raise ValueError(f"样本数超过 {MAX_SAMPLES} 上限，请拆分数据集")

    if not samples:
        raise ValueError("未解析出任何 (query, candidate) 样本")

    _validate(samples)
    return samples, {
        "total_rows": len(rows),
        "unlabeled_rows": unlabeled,
    }


def _grouped_candidates(row: Dict[str, Any]) -> Optional[List[Any]]:
    for key in ("candidates", "passages", "targets"):
        value = row.get(key)
        if isinstance(value, list):
            return value
    return None


def _from_grouped(
    row: Dict[str, Any],
    candidates: List[Any],
    default_subset: Optional[str],
    idx: int,
) -> List[RawSample]:
    if not candidates:
        raise ValueError("candidates 为空")
    q_text, q_img = _pick_side(row, _QUERY_TEXT_KEYS, _QUERY_IMAGE_KEYS, "query")
    if q_text is None and q_img is None:
        raise ValueError("缺少 query 文本或图片")
    subset = _pick_subset(row) or default_subset
    qid = _pick_qid(row, q_text, q_img, idx)

    out: List[RawSample] = []
    for c_idx, cand in enumerate(candidates):
        if not isinstance(cand, dict):
            raise ValueError(f"candidates[{c_idx}] 不是对象")
        t_text = _first_str(cand, ("text", "content", "target", "tgt", "value", "passage"))
        t_img = _first_str(cand, ("image", "image_path", "image_url", "img"))
        if t_text is None and t_img is None:
            raise ValueError(f"candidates[{c_idx}] 缺少文本或图片")
        label = _pick_label(cand)
        if label is None:
            raise ValueError(f"candidates[{c_idx}] 缺少 label（0/1）")
        out.append(
            RawSample(
                qid=qid,
                subset=subset or _infer_subset(q_text, q_img, t_text, t_img),
                query_text=q_text,
                query_image_ref=q_img,
                target_text=t_text,
                target_image_ref=t_img,
                label=label,
                metadata=_extra_metadata(cand),
            )
        )
    return out


def _from_pair(
    row: Dict[str, Any], default_subset: Optional[str], idx: int
) -> Tuple[List[RawSample], bool]:
    q_text, q_img = _pick_side(row, _QUERY_TEXT_KEYS, _QUERY_IMAGE_KEYS, "query")
    if q_text is None and q_img is None:
        raise ValueError("缺少 query 文本或图片（qry/query/qry_text 等字段）")
    subset = _pick_subset(row) or default_subset
    qid = _pick_qid(row, q_text, q_img, idx)

    pos_text = _first_str(row, _POS_TEXT_KEYS)
    pos_img = _first_str(row, _POS_IMAGE_KEYS)
    neg_text = _first_str(row, _NEG_TEXT_KEYS)
    neg_img = _first_str(row, _NEG_IMAGE_KEYS)

    out: List[RawSample] = []
    if pos_text is not None or pos_img is not None:
        out.append(
            RawSample(
                qid=qid,
                subset=subset or _infer_subset(q_text, q_img, pos_text, pos_img),
                query_text=q_text,
                query_image_ref=q_img,
                target_text=pos_text,
                target_image_ref=pos_img,
                label=1,
                metadata={},
            )
        )
        if neg_text is not None or neg_img is not None:
            out.append(
                RawSample(
                    qid=qid,
                    subset=subset or _infer_subset(q_text, q_img, neg_text, neg_img),
                    query_text=q_text,
                    query_image_ref=q_img,
                    target_text=neg_text,
                    target_image_ref=neg_img,
                    label=0,
                    metadata={},
                )
            )
        return out, True

    t_text, t_img = _pick_side(row, _TARGET_TEXT_KEYS, _TARGET_IMAGE_KEYS, "target")
    if t_text is None and t_img is None:
        raise ValueError("缺少候选文本或图片（tgt/target/pos_text 等字段）")

    label = _pick_label(row)
    out.append(
        RawSample(
            qid=qid,
            subset=subset or _infer_subset(q_text, q_img, t_text, t_img),
            query_text=q_text,
            query_image_ref=q_img,
            target_text=t_text,
            target_image_ref=t_img,
            label=label if label is not None else 0,
            metadata=_extra_metadata(row),
        )
    )
    return out, label is not None


def _pick_side(
    row: Dict[str, Any],
    text_keys: Tuple[str, ...],
    image_keys: Tuple[str, ...],
    kind: str,
) -> Tuple[Optional[str], Optional[str]]:
    text: Optional[str] = None
    image: Optional[str] = None

    for key in text_keys:
        if key not in row:
            continue
        value = row[key]
        if isinstance(value, dict):
            nested_text = _first_str(value, ("text", "content", "question", "value"))
            nested_img = _first_str(
                value, ("image", "image_path", "image_url", "img", "uri")
            )
            text = text if text is not None else nested_text
            image = image if image is not None else nested_img
        elif isinstance(value, str) and value.strip():
            # 通用字段 "query"/"qry" 若值看起来是图片路径，按图片处理
            if key in ("query", "qry") and _looks_like_image(value):
                image = image or value.strip()
            else:
                text = text if text is not None else value.strip()
        if text is not None and image is not None:
            break

    for key in image_keys:
        if key in row and image is None:
            value = row[key]
            if isinstance(value, str) and value.strip():
                image = value.strip()
            elif isinstance(value, dict):
                image = _first_str(value, ("url", "path", "image", "uri"))
        if image is not None:
            break
    return text, image


def _first_str(row: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[str]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return None


def _pick_label(row: Dict[str, Any]) -> Optional[int]:
    for key in _LABEL_KEYS:
        if key not in row:
            continue
        value = row[key]
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (int, float)):
            return 1 if value > 0 else 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("1", "true", "yes", "positive", "pos"):
                return 1
            if lowered in ("0", "false", "no", "negative", "neg"):
                return 0
    return None


def _pick_qid(
    row: Dict[str, Any], q_text: Optional[str], q_img: Optional[str], idx: int
) -> str:
    for key in _QID_KEYS:
        value = row.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()[:200]
    # 无显式 qid：用查询内容哈希把同一 query 的不同候选归到一组
    digest = hashlib.sha1(
        f"{q_text or ''}|{q_img or ''}".encode("utf-8")
    ).hexdigest()[:16]
    return f"q_{digest}"


def _pick_subset(row: Dict[str, Any]) -> Optional[str]:
    for key in _SUBSET_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:100]
    return None


def _infer_subset(
    q_text: Optional[str],
    q_img: Optional[str],
    t_text: Optional[str],
    t_img: Optional[str],
) -> str:
    return f"{'I' if q_img else 'T'}→{'I' if t_img else 'T'}"


def _extra_metadata(row: Dict[str, Any]) -> Dict[str, Any]:
    skip = set(
        _QUERY_TEXT_KEYS + _QUERY_IMAGE_KEYS + _TARGET_TEXT_KEYS + _TARGET_IMAGE_KEYS
        + _POS_TEXT_KEYS + _POS_IMAGE_KEYS + _NEG_TEXT_KEYS + _NEG_IMAGE_KEYS
        + _LABEL_KEYS + _QID_KEYS + _SUBSET_KEYS
    ) | {"candidates", "passages", "targets", "query", "qry", "target", "tgt"}
    extra = {k: v for k, v in row.items() if k not in skip}
    return extra if isinstance(extra, dict) else {}


def _looks_like_image(value: str) -> bool:
    lowered = value.lower().split("?", 1)[0]
    return lowered.startswith(("http://", "https://", "data:image/")) or any(
        lowered.endswith(ext) for ext in IMAGE_EXTS
    )


def _validate(samples: List[RawSample]) -> None:
    positives: Dict[str, int] = {}
    seen_query: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
    for sample in samples:
        if sample.query_text is None and sample.query_image_ref is None:
            raise ValueError(f"qid={sample.qid} 的 query 侧为空")
        if sample.target_text is None and sample.target_image_ref is None:
            raise ValueError(f"qid={sample.qid} 的 candidate 侧为空")
        if sample.label == 1:
            positives[sample.qid] = positives.get(sample.qid, 0) + 1
        seen_query.setdefault(sample.qid, (sample.query_text, sample.query_image_ref))

    missing = [qid for qid in seen_query if positives.get(qid, 0) == 0]
    if missing:
        preview = "、".join(missing[:MAX_REPORTED_ERRORS])
        raise ValueError(
            f"以下 {len(missing)} 个查询没有任何 label=1 的正例：{preview}"
            "（label 字段缺失或全为 0，无法计算召回）"
        )
