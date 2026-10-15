# 评测/训练数据通用 Schema 探测
#
# 解决「怎么知道该统计哪个字段」的问题：
#   1. 语义角色识别 —— 任意列名映射到规范角色（question/answer/conversation/…）
#   2. 值形态推断 —— 判定值是标量/数组/带 role 的对话/带 text 的段落…
#   3. 能力推导   —— 由角色与形态组合出「这份数据能做什么统计」
#
# 有了这一层，统计器按能力注册与探针（probe）动态选取，
# 新增一种数据形态只需新增一个统计器，不必改归一化与画像主流程。
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# 语义角色
# ---------------------------------------------------------------------------
ROLE_QUESTION = "question"
ROLE_ANSWER = "answer"
ROLE_INSTRUCTION = "instruction"
ROLE_RESPONSE = "response"
ROLE_CHOICES = "choices"
ROLE_CONTEXT = "context"
ROLE_PASSAGES = "passages"
ROLE_CONVERSATION = "conversation"
ROLE_PREFERENCE = "preference"
ROLE_SCORE = "score"
ROLE_SUBJECT = "subject"
ROLE_DIFFICULTY = "difficulty"
ROLE_TEXT = "text"

# 角色别名表：键统一转小写后匹配。顺序即优先级。
ROLE_ALIASES: Dict[str, List[str]] = {
    # 对话优先于单轮：conversation 的别名更具体，避免 messages 被当成 text
    ROLE_CONVERSATION: [
        "messages", "conversation", "conversations", "chat", "dialog",
        "dialogue", "history", "turns", "multi_turn", "多轮对话",
    ],
    ROLE_PREFERENCE: ["chosen", "rejected", "preferred", "response_a", "response_b"],
    ROLE_CHOICES: [
        "choices", "options", "candidates", "distractors", "answer_options",
        "choices_list", "选项", "answers_options",
    ],
    ROLE_QUESTION: [
        "question", "query", "prompt", "problem", "stem", "input", "instruction",
        "query_text", "问题",
    ],
    ROLE_ANSWER: [
        "answer", "answerkey", "answer_key", "label", "target", "gold",
        "gold_answer", "correct_answer", "correctanswer", "solution",
        "final_answer", "output", "response", "answer_text", "答案",
    ],
    ROLE_INSTRUCTION: ["instruction", "human", "user", "user_message"],
    ROLE_RESPONSE: ["response", "gpt", "assistant", "bot", "assistant_message"],
    ROLE_CONTEXT: [
        "context", "contexts", "paragraph", "passage", "document", "reference",
        "background", "gold_contexts", "documents",
    ],
    ROLE_PASSAGES: [
        "passages", "candidates_passages", "docs", "positive_passages",
        "negative_passages", "positive", "negative", "positives", "negatives",
    ],
    ROLE_SCORE: ["score", "rating", "reward", "quality", "similarity", "grade", "value"],
    ROLE_SUBJECT: [
        "subject", "discipline", "category", "topic", "domain", "field",
        "knowledge_point", "task", "task_type", "学科", "类别",
    ],
    ROLE_DIFFICULTY: ["difficulty", "level", "hardness", "难度", "级别"],
    ROLE_TEXT: ["text", "content", "body", "raw_content", "cleaned_content", "document"],
}


class ValueKind:
    """值形态（决定统计方式）"""
    EMPTY = "empty"
    NUMBER = "number"
    BOOL = "bool"
    STRING = "string"
    LIST_SCALAR = "list_scalar"        # ["a","b"] 或 [1,2,3]
    LIST_OBJECT = "list_object"        # [{...}, {...}]
    CONVERSATION = "conversation"      # 带 role/content 的对象列表
    OBJECT = "object"


class FieldInfo:
    """单个字段的探测结果"""
    __slots__ = ("name", "kind", "roles", "coverage", "samples")

    def __init__(self, name: str, kind: str, roles: List[str], coverage: float, samples: int):
        self.name = name
        self.kind = kind
        self.roles = roles
        self.coverage = coverage
        self.samples = samples

    @property
    def role(self) -> Optional[str]:
        return self.roles[0] if self.roles else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.name,
            "kind": self.kind,
            "roles": self.roles,
            "coverage": round(self.coverage, 4),
        }


class Schema:
    """一份数据集的结构画像"""
    def __init__(self, fields: Dict[str, FieldInfo]):
        self.fields = fields
        # role -> field name（取第一个命中该角色的字段）
        self._by_role: Dict[str, str] = {}
        for name, info in fields.items():
            for role in info.roles:
                self._by_role.setdefault(role, name)

    def field_for(self, role: str) -> Optional[str]:
        return self._by_role.get(role)

    def kind_of(self, role: str) -> Optional[str]:
        name = self.field_for(role)
        return self.fields[name].kind if name else None

    def has(self, role: str) -> bool:
        return role in self._by_role

    def role_of(self, field_name: str) -> Optional[str]:
        info = self.fields.get(field_name)
        return info.role if info else None

    @property
    def capabilities(self) -> Set[str]:
        return derive_capabilities(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fields": [f.to_dict() for f in self.fields.values()],
            "role_fields": dict(self._by_role),
            "capabilities": sorted(self.capabilities),
        }


# ---------------------------------------------------------------------------
# 值形态推断
# ---------------------------------------------------------------------------
_ROLE_KEYS = {"role", "from", "speaker", "author"}
_CONTENT_KEYS = {"content", "text", "value", "message"}
_RELEVANCE_KEYS = {"relevance", "relevance_label", "label", "score", "grade", "is_relevant"}


def _kind_of_value(value: Any) -> str:
    if value is None:
        return ValueKind.EMPTY
    if isinstance(value, bool):
        return ValueKind.BOOL
    if isinstance(value, (int, float)):
        return ValueKind.NUMBER
    if isinstance(value, str):
        return ValueKind.STRING
    if isinstance(value, dict):
        return ValueKind.OBJECT
    if isinstance(value, (list, tuple)):
        if not value:
            return ValueKind.LIST_SCALAR
        if all(isinstance(x, dict) for x in value):
            # 带 role/content → 对话；带 text/relevance → 段落列表
            keysets = [set(x.keys()) for x in value if isinstance(x, dict)]
            if keysets and all(k & _ROLE_KEYS for k in keysets):
                return ValueKind.CONVERSATION
            if keysets and all((k & _CONTENT_KEYS) for k in keysets):
                if any(k & _RELEVANCE_KEYS for k in keysets):
                    return ValueKind.LIST_OBJECT
                return ValueKind.LIST_OBJECT
            return ValueKind.LIST_OBJECT
        return ValueKind.LIST_SCALAR
    return ValueKind.STRING


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(key).lower())


# 规范化后的别名表
_NORMALIZED_ALIASES: Dict[str, List[str]] = {
    role: {_normalize_key(a) for a in aliases}
    for role, aliases in ROLE_ALIASES.items()
}


def _roles_for(name: str, kind: str) -> List[str]:
    """字段名 → 命中的语义角色（按别名表优先级排序）"""
    key = _normalize_key(name)
    hit: List[str] = []
    for role, aliases in ROLE_ALIASES.items():
        if key in aliases:
            hit.append(role)
    # 形态与角色一致性修正：choices 字段是字符串数组而非对象列表时仍算 choices
    if ROLE_CHOICES in hit and kind == ValueKind.STRING:
        hit.append(ROLE_TEXT)  # 单个选项串，文本也可
    return hit


# ---------------------------------------------------------------------------
# 能力推导
# ---------------------------------------------------------------------------
CAP_HAS_CONVERSATION = "conversation"      # 可做轮次画像
CAP_HAS_CHOICES = "choices"                # 可做答案位置偏置
CAP_HAS_ANSWER = "answer"                  # 有标准答案
CAP_HAS_PASSAGES = "passages"              # 可做检索/重排画像
CAP_HAS_POSITIVE_NEGATIVE = "positive_negative"
CAP_HAS_SCORE = "score"                    # 可做分布/质量分
CAP_HAS_SUBJECT = "subject"                # 可做能力覆盖
CAP_HAS_DIFFICULTY = "difficulty"
CAP_HAS_TEXT = "text"                      # 纯语料，可做长度画像


def derive_capabilities(schema: "Schema") -> Set[str]:
    caps: Set[str] = set()
    # 对话字段：命中别名即认定，不再要求形态严格等于 CONVERSATION。
    # UltraChat 的 history 是纯字符串数组(LIST_SCALAR)、dialogue 可能是
    # JSON 字符串(STRING)，两者都是合法对话载体——形态检查过严会漏掉这两种
    # （实测踩过：轮次算对了，但能力集里没有 conversation，统计器不会被启用）。
    # 形态检查只用于「字段名不在别名表、需额外发现对话字段」的场景。
    if schema.has(ROLE_CONVERSATION) or schema.has(ROLE_PREFERENCE):
        caps.add(CAP_HAS_CONVERSATION)

    choices_field = schema.field_for(ROLE_CHOICES)
    if choices_field and schema.fields[choices_field].kind in (
        ValueKind.LIST_SCALAR, ValueKind.LIST_OBJECT, ValueKind.STRING
    ):
        caps.add(CAP_HAS_CHOICES)

    if schema.has(ROLE_ANSWER):
        caps.add(CAP_HAS_ANSWER)
    if schema.has(ROLE_CONTEXT) or schema.has(ROLE_PASSAGES):
        caps.add(CAP_HAS_PASSAGES)

    # 正负例：出现 positive/negative 任一别名即可
    norm_keys = {_normalize_key(f) for f in schema.fields}
    for role in (ROLE_PASSAGES,):
        if schema.has(role):
            caps.add(CAP_HAS_PASSAGES)
    if any("positive" in k or "pos" == k for k in norm_keys) and \
       any("negative" in k or "neg" == k for k in norm_keys):
        caps.add(CAP_HAS_POSITIVE_NEGATIVE)

    if schema.has(ROLE_SCORE):
        caps.add(CAP_HAS_SCORE)
    if schema.has(ROLE_SUBJECT):
        caps.add(CAP_HAS_SUBJECT)
    if schema.has(ROLE_DIFFICULTY):
        caps.add(CAP_HAS_DIFFICULTY)
    if schema.has(ROLE_TEXT):
        caps.add(CAP_HAS_TEXT)
    return caps


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def detect_schema(
    records: List[Dict[str, Any]],
    max_scan: int = 500,
) -> Schema:
    """从原始记录探测 schema。只看前 max_scan 条即可稳定判定结构。

    刻意不依赖归一化层：任意格式的数据都能先被识别出结构，
    再决定用哪些统计器，避免「先硬编码字段、再补统计」的死循环。
    """
    sample = [r for r in records[:max_scan] if isinstance(r, dict)]
    if not sample:
        return Schema({})

    # 统计每个字段的覆盖率与形态众数
    field_values: Dict[str, List[Any]] = {}
    for record in sample:
        for key, value in record.items():
            field_values.setdefault(key, []).append(value)

    total = len(sample)
    fields: Dict[str, FieldInfo] = {}
    for name, values in field_values.items():
        non_empty = [v for v in values if v not in (None, "", [], {})]
        coverage = len(non_empty) / total
        kinds: Dict[str, int] = {}
        for value in non_empty[:100]:
            k = _kind_of_value(value)
            kinds[k] = kinds.get(k, 0) + 1
        kind = max(kinds.items(), key=lambda kv: kv[1])[0] if kinds else ValueKind.EMPTY
        fields[name] = FieldInfo(
            name=name,
            kind=kind,
            roles=_roles_for(name, kind),
            coverage=coverage,
            samples=len(non_empty),
        )

    # 形态兜底：字段名不在别名表里，但值形态是对话 → 也认作 conversation
    for info in fields.values():
        if info.kind == ValueKind.CONVERSATION and ROLE_CONVERSATION not in info.roles:
            info.roles.insert(0, ROLE_CONVERSATION)

    return Schema(fields)


# ---------------------------------------------------------------------------
# 对话轮次统计（通用实现：不假设字段叫 messages）
# ---------------------------------------------------------------------------
def extract_conversation(record: Dict[str, Any], field_name: str) -> List[Dict[str, Any]]:
    """按探测到的对话字段取值，兼容多种承载形态。"""
    raw = record.get(field_name)
    if raw is None:
        return []
    if isinstance(raw, str):
        # JSON 字符串
        s = raw.strip()
        if s[:1] not in "[{":
            return []
        import json
        try:
            raw = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return []
    if isinstance(raw, dict):
        raw = raw.get("messages") or raw.get("turns") or []
    if not isinstance(raw, list):
        return []

    out: List[Dict[str, Any]] = []
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            role = item.get("role") or item.get("from") or item.get("speaker")
            content = item.get("content") or item.get("text") or item.get("value")
            out.append({"role": str(role or ""), "content": content})
        elif isinstance(item, str):
            # UltraChat 形态：纯字符串按 user/assistant 交替
            out.append({"role": "user" if i % 2 == 0 else "assistant", "content": item})
    return out


def count_rounds(conversation: List[Dict[str, Any]]) -> int:
    """对话轮次 = user 消息数。

    不用 len(messages)：标准 [{user},{assistant}] 是 1 轮 2 条消息，
    按条数统计会把「1 轮问答」显示成「2 轮」，量纲就错了。
    没有 user 角色时按 user/assistant 交替推断。
    """
    if not conversation:
        return 0
    user_msgs = sum(1 for m in conversation if (m.get("role") or "").lower() in ("user", "human"))
    if user_msgs:
        return user_msgs
    return (len(conversation) + 1) // 2