"""生成内置评测集样例（离线可用，格式对齐各开源评测集的真实列结构）。

设计原则：样例必须是「真实格式」而非简化玩具，否则画像引擎的兼容性保证无从验证。
每个样例的列名都取自该评测集的真实 schema：
  ceval_middle_school_mathematics → 同级列 A/B/C/D + answer（CEval 真实形态）
  mmlu_abstract_algebra          → choices 数组 + 0-based answer（MMLU 真实形态）
  gsm8k                          → question + "#### 数值" 答案（GSM8K 真实形态）
  stsb_cn                        → sentence1/sentence2/score（STS-B 真实形态）
  miracl_retrieval               → query + positive/negative_passages（MIRACL 真实形态）
  passage_relevance              → passages[{text,relevance}]（重排评测真实形态）

其中 ceval / mmlu 刻意共用一部分知识点题，用于演示集间重叠与答案冲突检测。
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

OUT_DIR = Path(__file__).resolve().parent
OUT_DIR.mkdir(parents=True, exist_ok=True)

random.seed(20261014)

# ---------------------------------------------------------------------------
# LLM：C-Eval 式多学科选择题（中文，同级列 A/B/C/D）
# ---------------------------------------------------------------------------
CEVAL_SUBJECTS = [
    "初中数学", "高中数学", "高中物理", "大学物理", "大学化学",
    "计算机网络", "数据结构", "操作系统", "中国近现代史", "世界历史",
]

SHARED_KNOWLEDGE = [
    ("下列关于三角函数的说法正确的是", ["正弦函数是奇函数", "余弦函数是奇函数", "正切函数在定义域内单调递增", "正弦函数是偶函数"], 0),
    ("下列数据结构中属于线性结构的是", ["栈", "树", "图", "散列表"], 0),
    ("计算机操作系统的主要功能是", ["管理软硬件资源", "仅负责网络通信", "仅负责文件存储", "仅负责内存分配"], 0),
    ("下列关于电磁感应现象的说法正确的是", ["闭合回路磁通量变化会产生感应电动势", "静止导体切割磁力线会产生感应电流", "感应电动势与磁通量变化率成正比", "感应电流方向总是与磁通量同向"], 2),
    ("下列关于氧化还原反应的说法正确的是", ["化合价升降是判断依据", "得电子一定被氧化", "失电子一定被还原", "氧化剂发生还原反应"], 0),
]

DISTRACTOR_POOL = [
    "该说法在所有条件下均成立，无需附加前提",
    "这一结论可以通过简单举例直接验证",
    "这种理解在多数入门材料中被广泛采用",
    "上述表述与实际测量结果完全一致",
]


def build_ceval(n=200):
    rows = []
    for i in range(n):
        subject = CEVAL_SUBJECTS[i % len(CEVAL_SUBJECTS)]
        if i < len(SHARED_KNOWLEDGE) * 8:
            stem, opts, correct = SHARED_KNOWLEDGE[(i // 8) % len(SHARED_KNOWLEDGE)]
            choices = list(opts)
            correct_idx = correct
        else:
            stem = f"在{subject}中，关于「知识点{i}」的下列说法正确的是"
            choices = [f"关于知识点{i}的说法甲", f"关于知识点{i}的说法乙",
                       f"关于知识点{i}的说法丙", f"关于知识点{i}的说法丁"]
            # 轻微偏斜（真实评测集也有偏斜），让画像能展示答案位置分布
            correct_idx = 0 if random.random() < 0.34 else random.randrange(4)
        rows.append({
            "id": f"ceval_{subject}_{i}",
            "question": f"{stem}？",
            "A": choices[0], "B": choices[1], "C": choices[2], "D": choices[3],
            "answer": "ABCD"[correct_idx],
            "explanation": f"依据{subject}的基本定义，正确答案为{choices[correct_idx]}。",
            "subject": subject,
        })
    return rows


# ---------------------------------------------------------------------------
# LLM：MMLU 式英文选择题（choices 数组 + 0-based 索引答案）
# ---------------------------------------------------------------------------
MMLU_SUBJECTS = ["abstract_algebra", "anatomy", "astronomy", "business_ethics",
                 "clinical_knowledge", "computer_security", "econometrics",
                 "high_school_biology", "logical_fallacies", "prehistory"]


def build_mmlu(n=180):
    rows = []
    for i in range(n):
        subject = MMLU_SUBJECTS[i % len(MMLU_SUBJECTS)]
        if i < 25:  # 与 C-Eval 共享的 5 道题（英文译本），制造重叠
            stem, opts, correct = SHARED_KNOWLEDGE[(i // 5) % len(SHARED_KNOWLEDGE)]
            choices = list(opts)
            correct_idx = correct
        else:
            stem = f"Which of the following best describes concept {i} in {subject}?"
            choices = [f"Option {i}-alpha", f"Option {i}-beta", f"Option {i}-gamma", f"Option {i}-delta"]
            correct_idx = random.randrange(4)
        rows.append({
            "question": stem,
            "choices": choices,
            "answer": correct_idx,  # MMLU 真实形态：0-based 索引
            "subject": subject.replace("_", " ").title(),
        })
    return rows


# ---------------------------------------------------------------------------
# LLM：GSM8K 式数学生成题（答案以 "#### 数值" 结尾）
# ---------------------------------------------------------------------------
def build_gsm8k(n=150):
    rows = []
    for i in range(n):
        a, b = random.randint(12, 96), random.randint(3, 48)
        rows.append({
            "question": (
                f" Natalia has {a} clips. She gives {b} clips to her brother, "
                f"then buys {a // 3 + 5} more clips. How many clips does she have now?"
            ),
            "answer": (
                f"Natalia starts with {a} clips.\n"
                f"She gives away {b} clips: {a} - {b} = {a - b}\n"
                f"Then she buys more: {a - b} + {a // 3 + 5} = {a - b + a // 3 + 5}\n"
                f"#### {a - b + a // 3 + 5}"
            ),
        })
    return rows


# ---------------------------------------------------------------------------
# Embedding：STS-B 式中文句对相似度
# ---------------------------------------------------------------------------
PAIRS = [
    ("一个男人正在弹吉他。", "一个男人正在演奏乐器。", 4.6),
    ("一只猫躺在沙发上。", "一只猫咪在客厅休息。", 3.8),
    ("汽车在公路上行驶。", "飞机在跑道上起飞。", 0.6),
    ("他在厨房里做饭。", "她在阳台上浇花。", 0.2),
    ("公司发布了新的年度报告。", "企业公布了本年度财务报告。", 4.2),
    ("这部电影情节感人。", "这部影片的剧情十分动人。", 4.8),
    ("学生们在教室里上课。", "医生在医院里看病。", 0.4),
    ("工程师部署了新的服务。", "运维人员更新了监控配置。", 2.1),
]


def build_stsb_cn(n=140):
    rows = []
    for i in range(n):
        s1, s2, score = PAIRS[i % len(PAIRS)]
        rows.append({
            "sentence1": s1,
            "sentence2": s2,
            "score": score,
            "genre": "news" if score < 2 else "main",
        })
    return rows


# ---------------------------------------------------------------------------
# Embedding：MIRACL 式检索评测（query + 正负例段落）
# ---------------------------------------------------------------------------
RETRIEVAL_TOPICS = [
    ("新能源汽车有哪些主要的电池技术路线？",
     ["主流技术路线包括三元锂电池和磷酸铁锂电池，各自的能量密度与安全性取舍不同。",
      "动力电池的成本构成中，正极材料占比最高，锂资源价格波动影响显著。"],
     ["今天中午吃了火锅，味道还不错。", "周末去公园散步的人很多。"]),
    ("如何申请订单退款？",
     ["在订单详情页点击「申请售后」，选择退款原因并提交即可，一般 3-5 个工作日到账。",
      "退款审核通过后，款项将原路返回至支付账户。"],
     ["配送范围覆盖全国大部分地区。", "客服电话工作时间是 9 点到 18 点。"]),
    ("什么是重排序模型（reranker）？",
     ["重排模型对召回阶段的候选文档做精细相关性打分，提升 top-k 结果质量。",
      "常见的重排模型包括 cross-encoder 架构，如 bge-reranker。"],
     ["向量数据库支持 HNSW 与 IVF 索引结构。", "推荐系统的召回阶段追求高吞吐。"]),
    ("数据库索引的作用是什么？",
     ["索引能显著加速特定字段的查询，但会降低写入性能并占用额外存储。",
      "联合索引的列顺序会影响能否命中最左前缀匹配。"],
     ["事务隔离级别包括读未提交、读已提交、可重复读和串行化。", "分库分表可以缓解单库数据量过大的问题。"]),
]


def build_miracl(n=160):
    rows = []
    for i in range(n):
        q, pos, neg = RETRIEVAL_TOPICS[i % len(RETRIEVAL_TOPICS)]
        rows.append({
            "query_id": f"miracl_{i}",
            "query": q,
            "positive_passages": [{"text": p} for p in pos],
            "negative_passages": [{"text": n_} for n_ in neg],
        })
    return rows


# ---------------------------------------------------------------------------
# Reranker：段落相关性打分（passages + relevance 分级）
# ---------------------------------------------------------------------------
RELEVANCE_SETS = [
    ("如何提高向量检索的召回率？",
     [("通过查询改写扩展召回范围，或结合稀疏与稠密混合检索。", 2),
      ("调整 HNSW 的 ef_search 参数可以提升召回率但降低速度。", 1),
      ("推荐使用 BM25 与向量检索做混合排序。", 2),
      ("今天天气晴朗，适合户外活动。", 0),
      ("数据库事务需要考虑隔离级别。", 0)]),
    ("什么是 nDCG 指标？",
     [("nDCG 是归一化折损累积增益，衡量排序质量并考虑位置折损。", 2),
      ("它对排名靠前的相关文档赋予更高权重。", 1),
      ("MRR 只关注第一个正确结果的位置。", 1),
      ("这款手机的外观设计非常时尚。", 0)]),
]


def build_rerank(n=150):
    rows = []
    for i in range(n):
        q, passages = RELEVANCE_SETS[i % len(RELEVANCE_SETS)]
        rows.append({
            "query": q,
            "passages": [{"text": t, "relevance": r} for t, r in passages],
        })
    return rows


def write(name, rows):
    path = OUT_DIR / f"{name}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  {name:<26} {len(rows):>4} 条  {path.name}")


if __name__ == "__main__":
    print(f"写入 {OUT_DIR}")
    write("ceval_middle_school_mathematics", build_ceval())
    write("mmlu_abstract_algebra", build_mmlu())
    write("gsm8k", build_gsm8k())
    write("stsb_cn", build_stsb_cn())
    write("miracl_retrieval", build_miracl())
    write("passage_relevance", build_rerank())
    print("完成")