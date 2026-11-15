# 内置基准评测集：随应用启动自动入库（幂等），并支持从 API 一键重建
#
# 新装环境里数据集是空的，「调用 → 评估 → 归因」整条链路没有素材可跑。
# 内置一份原创、分层的基准评测集，让新环境开箱即可发起评估。
#
# 有效性设计（对标 jevbench 等 benchmark 工程实践）：
# - 原创：题目全部为本项目原创撰写，不取自公开基准，规避预训练/评测污染；
# - 分层：difficulty（easy/medium/hard）× question_type（simple/complex/multi_hop）
#   双维度标注，加载时校验每个组合都有样本，防止难度或题型坍缩成单一标签；
# - 冻结：文件内容 sha256 记录在数据集 dataset_metadata 里，内容变更视为版本
#   升级——未被评估/调用引用过的数据集原地重建，已被引用的跳过升级并告警
#   （历史评估结果按 qa_record id 引用，原地重建会撕断关联）；
# - 质量报告：入库时统计难度/题型/能力/学科分布、题干与答案长度、集内去重率，
#   存入 dataset_metadata.quality_report，随数据集一起可查可展示。
import hashlib
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dataset import Dataset, QARecord
from app.models.evaluation import Evaluation
from app.models.invocation import InvocationBatch
from app.services.documents import refresh_dataset_stats

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "builtin_benchmarks"

VALID_DIFFICULTIES = ("easy", "medium", "hard")
VALID_QUESTION_TYPES = ("simple", "complex", "multi_hop")

# 内置基准注册表：新增基准在这里登记，启动时自动入库
BUILTIN_BENCHMARKS = [
    {
        "benchmark_id": "rag_qa_zh_v1",
        "name": "JQ-Eval 中文综合问答基准 v1",
        "version": "v1",
        "filename": "rag_qa_benchmark_v1.jsonl",
        "description": (
            "原创中文综合问答基准：60 题，覆盖 easy/medium/hard 难度与 "
            "simple/complex/multi_hop 题型的全部组合，能力维度含事实记忆、定义理解、"
            "因果解释、数值计算、对比分析、时序推理等。题目不取自公开基准，"
            "可放心用于开箱评估与版本间回归对比。"
        ),
        "language": "zh",
        "license": "proprietary-original",
    },
]


def get_benchmark_meta(benchmark_id: str) -> dict:
    for meta in BUILTIN_BENCHMARKS:
        if meta["benchmark_id"] == benchmark_id:
            return meta
    raise ValueError(f"未知的内置基准: {benchmark_id}")


def _norm_question(text: str) -> str:
    """题干归一化，与 datasets.py 导入侧同一口径（空白折叠 + casefold）"""
    return " ".join((text or "").split()).casefold()


def load_benchmark_records(meta: dict) -> tuple[list[dict], str]:
    """加载并校验基准文件，返回 (记录列表, 文件内容 sha256)

    校验失败直接抛 ValueError：内置基准是「有效性」的招牌，
    与其带病入库，不如启动时就把问题暴露出来。
    """
    path = DATA_DIR / meta["filename"]
    if not path.exists():
        raise ValueError(f"基准文件不存在: {path}")
    raw = path.read_bytes()
    file_hash = hashlib.sha256(raw).hexdigest()

    records: list[dict] = []
    seen: dict[str, int] = {}
    for lineno, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{meta['filename']} 第{lineno}行不是合法 JSON: {e}")

        question = (item.get("question") or "").strip()
        answer = (item.get("answer") or "").strip()
        difficulty = (item.get("difficulty") or "").strip()
        question_type = (item.get("question_type") or "").strip()
        if not question or not answer:
            raise ValueError(f"{meta['filename']} 第{lineno}行缺少 question/answer")
        if difficulty not in VALID_DIFFICULTIES:
            raise ValueError(f"{meta['filename']} 第{lineno}行 difficulty 非法: {difficulty!r}")
        if question_type not in VALID_QUESTION_TYPES:
            raise ValueError(f"{meta['filename']} 第{lineno}行 question_type 非法: {question_type!r}")

        key = _norm_question(question)
        if key in seen:
            raise ValueError(
                f"{meta['filename']} 第{lineno}行题干与第{seen[key]}行重复（归一化后）"
            )
        seen[key] = lineno

        records.append({
            "seq": len(records),
            "question": question,
            "answer": answer,
            # 标准答案显式落列：生成类指标（correctness 等）都按 ground_truth 判分
            "ground_truth": answer,
            "difficulty": difficulty,
            "question_type": question_type,
            "ability": (item.get("ability") or "").strip() or None,
            "subject": (item.get("subject") or "").strip() or None,
        })

    if not records:
        raise ValueError(f"{meta['filename']} 没有可用样本")
    _check_coverage(meta, records)
    return records, file_hash


def _check_coverage(meta: dict, records: list[dict]) -> None:
    """难度 × 题型的每个组合都必须有样本

    分层的意义在于评估结果可按层拆解对比（弱模型是不是只会做 easy？
    多跳推理差是普遍现象还是个别学科？），任何一个组合为空都会让该层失去对照。
    """
    combos = {(r["difficulty"], r["question_type"]) for r in records}
    missing = [
        f"{d}/{t}"
        for d in VALID_DIFFICULTIES
        for t in VALID_QUESTION_TYPES
        if (d, t) not in combos
    ]
    if missing:
        raise ValueError(
            f"{meta['filename']} 缺少难度×题型组合样本: {', '.join(missing)}"
        )
    for d in VALID_DIFFICULTIES:
        count = sum(1 for r in records if r["difficulty"] == d)
        if count < 5:
            raise ValueError(
                f"{meta['filename']} 难度 {d} 只有 {count} 题，单层样本过少无统计意义"
            )


def compute_quality_report(records: list[dict]) -> dict:
    """基准质量画像：分布、去重率、长度统计，入库时冻结到数据集元数据里"""
    by_difficulty = Counter(r["difficulty"] for r in records)
    by_question_type = Counter(r["question_type"] for r in records)
    by_ability = Counter(r["ability"] for r in records if r["ability"])
    by_subject = Counter(r["subject"] for r in records if r["subject"])
    combos = Counter(f"{r['difficulty']}/{r['question_type']}" for r in records)

    def _len_stats(values):
        return {
            "min": min(values),
            "avg": round(sum(values) / len(values), 1),
            "max": max(values),
        }

    return {
        "total": len(records),
        "by_difficulty": dict(by_difficulty),
        "by_question_type": dict(by_question_type),
        "by_ability": dict(by_ability),
        "by_subject": dict(by_subject),
        "difficulty_x_type": dict(combos),
        # 加载器对题干做归一化去重并 fail-fast，这里复核口径永远应为 0
        "duplicate_rate": 0.0,
        "question_length": _len_stats([len(r["question"]) for r in records]),
        "answer_length": _len_stats([len(r["answer"]) for r in records]),
    }


def _qa_metadata(meta: dict, record: dict) -> dict:
    """单题元信息：溯源字段放 qa_metadata，评估详情里可按能力/学科拆解"""
    return {
        "benchmark_id": meta["benchmark_id"],
        "benchmark_seq": record["seq"],
        "ability": record["ability"],
        "subject": record["subject"],
    }


async def _find_builtin_dataset(db: AsyncSession, benchmark_id: str):
    rows = await db.execute(select(Dataset).where(Dataset.source_type == "builtin"))
    for dataset in rows.scalars():
        if (dataset.dataset_metadata or {}).get("benchmark_id") == benchmark_id:
            return dataset
    return None


async def _dataset_in_use(db: AsyncSession, dataset_id) -> bool:
    """是否已被评估任务/调用批次引用

    升版要原地重建 qa_records，而 Evaluation/InvocationBatch 都按
    dataset_id + qa_record id 关联着历史数据，删记录会撕断历史结果。
    被引用过的内置数据集不自动升版，只能等没有引用时再升级。
    """
    evals = await db.scalar(
        select(func.count(Evaluation.id)).where(Evaluation.dataset_id == dataset_id)
    )
    batches = await db.scalar(
        select(func.count(InvocationBatch.id)).where(InvocationBatch.dataset_id == dataset_id)
    )
    return bool(evals or batches)


def _add_records(db: AsyncSession, dataset_id, records: list[dict], meta: dict) -> None:
    for record in records:
        db.add(QARecord(
            dataset_id=dataset_id,
            question=record["question"],
            answer=record["answer"],
            ground_truth=record["ground_truth"],
            question_type=record["question_type"],
            difficulty=record["difficulty"],
            qa_metadata=_qa_metadata(meta, record),
        ))


def _benchmark_metadata(meta: dict, file_hash: str, report: dict) -> dict:
    return {
        "benchmark_id": meta["benchmark_id"],
        "benchmark_version": meta["version"],
        "language": meta["language"],
        "license": meta["license"],
        "file_hash": file_hash,
        "quality_report": report,
    }


async def provision_builtin_benchmark(db: AsyncSession, benchmark_id: str) -> dict:
    """把内置基准入库（幂等）：不存在则创建，文件内容变化则尝试升版"""
    meta = get_benchmark_meta(benchmark_id)
    records, file_hash = load_benchmark_records(meta)
    report = compute_quality_report(records)

    dataset = await _find_builtin_dataset(db, benchmark_id)
    created = False
    upgraded = False
    upgrade_skipped = False

    if dataset is None:
        dataset = Dataset(
            name=meta["name"],
            description=meta["description"],
            dataset_kind="evaluation",
            source_type="builtin",
            status="ready",
            dataset_metadata=_benchmark_metadata(meta, file_hash, report),
        )
        db.add(dataset)
        await db.flush()
        _add_records(db, dataset.id, records, meta)
        created = True
    else:
        stored = dataset.dataset_metadata or {}
        if stored.get("file_hash") != file_hash:
            if await _dataset_in_use(db, dataset.id):
                # 被评估/调用引用过的数据集不能原地重建，保历史一致性
                upgrade_skipped = True
                print(
                    f"[WARN] 内置基准 {benchmark_id} 文件内容已变化，"
                    f"但数据集已被评估/调用引用，跳过升版（记录哈希 {stored.get('file_hash')[:8]}…"
                    f" → {file_hash[:8]}…）"
                )
            else:
                await db.execute(delete(QARecord).where(QARecord.dataset_id == dataset.id))
                _add_records(db, dataset.id, records, meta)
                dataset.dataset_metadata = _benchmark_metadata(meta, file_hash, report)
                dataset.status = "ready"
                upgraded = True

    # 每次都校正统计：即便内容没变，手工删过记录也能自愈
    await refresh_dataset_stats(db, dataset.id, mark_ground_truth=True)
    await db.commit()
    await db.refresh(dataset)

    return {
        "benchmark_id": benchmark_id,
        "dataset_id": dataset.id,
        "record_count": len(records),
        "created": created,
        "upgraded": upgraded,
        "upgrade_skipped": upgrade_skipped,
        "quality_report": report,
        "dataset": dataset,
    }


async def sync_builtin_benchmarks(db: AsyncSession) -> int:
    """把注册表里的内置基准全部入库（幂等，可重复执行）

    单个基准失败只告警不中断：种子数据出问题不能挡住应用启动。
    """
    created_total = 0
    for meta in BUILTIN_BENCHMARKS:
        try:
            result = await provision_builtin_benchmark(db, meta["benchmark_id"])
        except ValueError as e:
            print(f"[WARN] 内置基准 {meta['benchmark_id']} 校验失败，跳过: {e}")
            continue
        except Exception as e:  # noqa: BLE001 —— 启动路径兜底
            print(f"[WARN] 内置基准 {meta['benchmark_id']} 入库失败，跳过: {e}")
            continue
        created_total += 1 if result["created"] else 0
        state = "新建" if result["created"] else (
            "升版重建" if result["upgraded"] else (
                "升版跳过(已被引用)" if result["upgrade_skipped"] else "已存在"
            )
        )
        print(
            f"[OK] 内置基准 {meta['benchmark_id']} 就绪（{state}，"
            f"{result['record_count']} 题，dataset_id={result['dataset_id']}）"
        )
    return created_total


async def list_builtin_benchmarks(db: AsyncSession) -> list[dict]:
    """注册表 + 入库状态合并视图，供前端展示/一键导入"""
    rows = await db.execute(select(Dataset).where(Dataset.source_type == "builtin"))
    provisioned = {}
    for dataset in rows.scalars():
        benchmark_id = (dataset.dataset_metadata or {}).get("benchmark_id")
        if benchmark_id:
            provisioned[benchmark_id] = dataset

    items = []
    for meta in BUILTIN_BENCHMARKS:
        dataset = provisioned.get(meta["benchmark_id"])
        try:
            _, file_hash = load_benchmark_records(meta)
        except ValueError as e:
            # 文件坏了也要能列出并暴露问题，而不是让列表接口 500
            items.append({**meta, "load_error": f"{e or '基准文件校验失败'}", "dataset": None})
            continue

        item = {
            **meta,
            "file_hash": file_hash,
            "load_error": None,
            "dataset": None,
        }
        if dataset:
            stored = dataset.dataset_metadata or {}
            item["dataset"] = {
                "id": str(dataset.id),
                "name": dataset.name,
                "record_count": dataset.record_count,
                "status": dataset.status,
                "file_hash": stored.get("file_hash"),
                "version_match": stored.get("file_hash") == file_hash,
                "quality_report": stored.get("quality_report"),
            }
        items.append(item)
    return items
