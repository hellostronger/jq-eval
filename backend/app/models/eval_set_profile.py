# 评测集画像模型
#
# 与训练数据画像（training_data_records / training_data_profiles）对称，但记录形态不同：
# 评测集的核心不是「文本长什么样」，而是「怎么判分」，因此按 model_type 分派归一化：
#   llm       —— question → 选项/生成答案，考答题正确率
#   embedding —— query ↔ positive/negative passages，考向量检索排序质量
#   reranker  —— (query, passages[]) → relevance 标签，考重排质量
#   retrieval —— RAG 检索评测，query → gold 上下文/分片 id
#
# 两张表：
#   eval_set_records  —— 评测样本落库（原始 payload + 归一化列，可回读可重算）
#   eval_set_profiles —— 评测集级画像（题型/答案形态/能力覆盖/质量风险）
#
# 关键设计：question_hash 只含题干（归一化后），用于跨评测集去重与污染检测；
# 若用含答案的指纹比对，同一知识点在不同集里选项不同会漏判。qa_hash 含答案，
# 用于集内精确去重与「同题干不同答案」的答案冲突检测。
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from ..core.db_types import ArrayType, JSONType, UUIDType
from .base import BaseModel


class EvalSetRecord(BaseModel):
    """评测样本表（兼容任意评测集格式）"""
    __tablename__ = "eval_set_records"

    dataset_id = Column(UUIDType(as_uuid=True), ForeignKey("datasets.id"), nullable=False, index=True)
    seq = Column(Integer, default=0)  # 导入顺序，保证样本预览稳定

    # ---- 评测归属 ----
    model_type = Column(String(20), default="llm")  # llm/embedding/reranker/retrieval
    task_format = Column(String(20), default="other")  # mc/generate/judge/pair_similarity/retrieval/rerank/other
    answer_type = Column(String(20), nullable=True)  # single_choice/multi_choice/free_text/numeric/relevance/none

    # ---- 题面（llm / retrieval 为主）----
    question = Column(Text, nullable=True)
    contexts = Column(JSONType, default=list)  # gold 上下文 / 正例段落
    target_chunk_ids = Column(ArrayType(String), default=list)  # gold 分片 id（检索评测）

    # ---- 选择题答案形态（评测集独有，也是最有诊断价值的部分）----
    choices = Column(JSONType, default=list)      # 归一化后的选项文本列表
    choice_labels = Column(ArrayType(String), default=list)  # ["A","B","C","D"]
    answer_labels = Column(ArrayType(String), default=list)  # 正确项标签，多选时多个
    answer_text = Column(Text, nullable=True)     # 生成题参考答案 / 语义相似度数值答案
    explanation = Column(Text, nullable=True)      # 解析（存在性本身就是质量信号）

    # ---- embedding / reranker 专属 ----
    positive_texts = Column(JSONType, default=list)   # 正例段落文本
    negative_texts = Column(JSONType, default=list)   # 负例段落文本
    passages = Column(JSONType, default=list)         # reranker 的候选段落 [{text, relevance}]
    relevance_labels = Column(ArrayType(String), default=list)  # 每段的相关度标签（0/1/2…）
    pos_count = Column(Integer, default=0)   # 正例数
    neg_count = Column(Integer, default=0)   # 负例数

    # ---- 能力维度 ----
    subject = Column(String(100), nullable=True, index=True)  # 学科（多学科评测集）
    category = Column(String(100), nullable=True, index=True)  # 能力类别 / 任务类型
    difficulty = Column(String(20), nullable=True)            # 集自带的难度声明
    language = Column(String(20), nullable=True)              # zh/en/mixed/other
    split = Column(String(20), nullable=True)                 # test/validation/dev

    # ---- 长度与指纹 ----
    question_length = Column(Integer, default=0)
    context_length = Column(Integer, default=0)   # 上下文/正例总长度
    est_tokens = Column(Integer, default=0)
    question_hash = Column(String(64), nullable=True, index=True)  # ★ 仅题干，跨集污染检测
    qa_hash = Column(String(64), nullable=True, index=True)       # 题干+答案，集内精确去重

    payload = Column(JSONType, default=dict)          # 原始记录，原样保留（未知字段永不丢失）
    record_metadata = Column(JSONType, default=dict)  # repo/revision/license/等溯源字段

    dataset = relationship("Dataset", back_populates="eval_set_records")


class EvalSetProfile(BaseModel):
    """评测集画像表（数据集级画像 + 集间对比的依据）"""
    __tablename__ = "eval_set_profiles"

    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    dataset_id = Column(UUIDType(as_uuid=True), ForeignKey("datasets.id"), nullable=False, index=True)
    source = Column(String(50), default="dataset")  # dataset/sample/huggingface/upload
    benchmark_key = Column(String(100), nullable=True)  # ceval/mmlu/mteb/beir… 便于集间对齐

    # 归属
    model_type = Column(String(20), default="llm")  # llm/embedding/reranker/retrieval

    status = Column(String(20), default="pending")  # pending/running/completed/failed
    progress = Column(Integer, default=0)
    error = Column(Text, nullable=True)

    total_samples = Column(Integer, default=0)
    unique_samples = Column(Integer, default=0)
    duplicate_rate = Column(Float, default=0.0)
    sampled = Column(Boolean, default=False)  # 是否只统计了前 N 条
    tags = Column(ArrayType(String), default=list)

    # 画像结果（评测集专属维度）
    overview = Column(JSONType, nullable=True)        # 规模/长度/token
    task_profile = Column(JSONType, nullable=True)    # 题型分布 ★
    answer_profile = Column(JSONType, nullable=True)  # 选项数/答案位置偏置/答案长度 ★★ 最有诊断价值
    capability = Column(JSONType, nullable=True)      # 学科/类别/语言/难度 ★
    quality = Column(JSONType, nullable=True)         # 质量信号与风险
    schema_profile = Column(JSONType, nullable=True)  # 字段画像
    samples = Column(JSONType, nullable=True)         # 样本预览
    summary = Column(Text, nullable=True)             # 规则生成的自然语言摘要

    # LLM 深度分析（可选）：off=不调 LLM / sample=抽样 / full=逐条
    llm_mode = Column(String(20), default="off")
    llm_model_id = Column(UUIDType(as_uuid=True), nullable=True)
    llm_sample_size = Column(Integer, default=40)
    llm_analysis = Column(JSONType, nullable=True)

    source_meta = Column(JSONType, nullable=True)  # 外部来源元数据（HF 元信息等）
    completed_at = Column(DateTime, nullable=True)

    dataset = relationship("Dataset", back_populates="eval_set_profiles")