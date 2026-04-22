# 标注矫正LLM提示模板
from typing import List, Dict, Any


# 声明抽取提示
STATEMENT_EXTRACTION_PROMPT = """你是一个专业的文本分析专家。请从以下文本中提取语义级别的声明（statements）。

声明定义：一个声明是文本中表达的一个独立的事实、观点或信息单元。每个声明应该是可以被独立验证的。

请按以下格式输出声明列表，每行一个声明：
- 使用JSON数组格式
- 每个声明是一个字符串

示例输出：
["声明1的内容", "声明2的内容", "声明3的内容"]

注意：
1. 将复杂句子拆解为多个简单声明
2. 每个声明保持原文的语义，但使用简洁的表达
3. 不要添加原文中没有的信息
4. 去除冗余和重复的声明

文本内容：
{text}
"""


# 差异对比提示
DIFFERENCE_COMPARISON_PROMPT = """你是一个专业的文本对比分析专家。请对比以下两段文本的声明，找出它们之间的差异。

系统回复中的声明：
{system_statements}

标准答案中的声明：
{ground_truth_statements}

请分析差异并按以下JSON格式输出：
{
  "system_only": ["只在系统回复中出现的声明"],
  "ground_truth_only": ["只在标准答案中出现的声明"],
  "conflicting": [
    {
      "system_statement": "系统回复中的声明",
      "ground_truth_statement": "标准答案中的对应声明",
      "conflict_description": "冲突描述"
    }
  ]
}

注意：
1. 只关注语义层面的差异，忽略表达方式的细微差异
2. conflicting部分要明确指出冲突点
3. 如果两段文本含义相同但表达不同，不要标记为差异
"""


# 验证问题生成提示
VERIFICATION_QUESTION_PROMPT = """你是一个专业的问题生成专家。请根据以下差异声明生成验证问题。

差异声明：
{difference}

请生成一个验证问题，用于判断该声明是否在提供的分片文本中有证据支持。

要求：
1. 问题应该能通过检索分片来验证
2. 问题应该针对声明中的关键事实或观点
3. 问题应该是具体、明确的

请直接输出验证问题，不要添加额外解释。

差异声明：{statement}
差异类型：{diff_type}

验证问题：
"""


# 证据验证提示
EVIDENCE_VERIFICATION_PROMPT = """你是一个专业的证据分析专家。请判断以下分片是否支持给定的声明。

声明：{statement}

验证问题：{question}

分片内容：
{chunks}

请分析每个分片是否包含支持该声明的证据，并按以下JSON格式输出：
{
  "supported": true或false,
  "supporting_chunks": [
    {
      "chunk_index": 分片索引,
      "content": "支持该声明的分片内容片段",
      "relevance_score": 相关性评分(0-1)
    }
  ],
  "reason": "判断理由"
}

注意：
1. 只有当分片明确包含声明中的关键信息时才标记为支持
2. 相关性评分基于分片与声明的语义匹配程度
3. 如果没有分片支持该声明，supported应为false
"""


# 存疑判断提示
DOUBT_JUDGMENT_PROMPT = """你是一个专业的数据质量评估专家。请根据以下分析结果判断该QA数据是否存疑。

原始问题：{question}

系统回复：{system_answer}

标准答案：{ground_truth}

差异声明分析结果：
{difference_analysis}

证据验证结果：
{evidence_results}

请判断该QA数据是否存疑，并按以下JSON格式输出：
{
  "is_doubtful": true或false,
  "doubt_reason": "存疑理由（如果is_doubtful为true）",
  "summary": "分析摘要"
}

存疑判定标准：
1. 系统回复包含重要信息但标准答案缺失，且分片不支持该信息
2. 标准答案包含重要信息但系统回复缺失，且分片不支持该信息
3. 系统回复和标准答案存在关键冲突，且分片无法支持任何一方
4. 如果差异只是表达方式不同或次要信息差异，不标记为存疑
"""


def format_statement_extraction_prompt(text: str) -> str:
    """格式化声明抽取提示"""
    return STATEMENT_EXTRACTION_PROMPT.format(text=text)


def format_difference_comparison_prompt(
    system_statements: List[str],
    ground_truth_statements: List[str]
) -> str:
    """格式化差异对比提示"""
    return DIFFERENCE_COMPARISON_PROMPT.format(
        system_statements="\n".join([f"- {s}" for s in system_statements]),
        ground_truth_statements="\n".join([f"- {s}" for s in ground_truth_statements])
    )


def format_verification_question_prompt(
    statement: str,
    diff_type: str,
    difference: str
) -> str:
    """格式化验证问题生成提示"""
    return VERIFICATION_QUESTION_PROMPT.format(
        difference=difference,
        statement=statement,
        diff_type=diff_type
    )


def format_evidence_verification_prompt(
    statement: str,
    question: str,
    chunks: List[Dict[str, Any]]
) -> str:
    """格式化证据验证提示"""
    chunks_text = "\n".join([
        f"分片{i+1}:\n{chunk.get('content', '')}"
        for i, chunk in enumerate(chunks)
    ])
    return EVIDENCE_VERIFICATION_PROMPT.format(
        statement=statement,
        question=question,
        chunks=chunks_text
    )


def format_doubt_judgment_prompt(
    question: str,
    system_answer: str,
    ground_truth: str,
    difference_analysis: Dict[str, Any],
    evidence_results: List[Dict[str, Any]]
) -> str:
    """格式化存疑判断提示"""
    import json
    return DOUBT_JUDGMENT_PROMPT.format(
        question=question,
        system_answer=system_answer,
        ground_truth=ground_truth,
        difference_analysis=json.dumps(difference_analysis, ensure_ascii=False, indent=2),
        evidence_results=json.dumps(evidence_results, ensure_ascii=False, indent=2)
    )