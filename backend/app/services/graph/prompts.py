# LightRAG Prompts for Entity/Relation Extraction
from typing import Any

PROMPTS: dict[str, Any] = {}

# Delimiters
PROMPTS["DEFAULT_TUPLE_DELIMITER"] = "<|#|>"
PROMPTS["DEFAULT_COMPLETION_DELIMITER"] = "<|COMPLETE|>"

# Default entity types (Chinese)
DEFAULT_ENTITY_TYPES_CN = [
    "人物", "组织", "地点", "事件", "概念",
    "方法", "产品", "数据", "物品", "自然对象"
]

# Default entity types (English)
DEFAULT_ENTITY_TYPES_EN = [
    "Person", "Organization", "Location", "Event", "Concept",
    "Method", "Product", "Data", "Artifact", "NaturalObject"
]

PROMPTS["entity_extraction_system_prompt"] = """---Role---
You are a Knowledge Graph Specialist responsible for extracting entities and relationships from the input text.

---Instructions---
1.  **Entity Extraction & Output:**
    *   **Identification:** Identify clearly defined and meaningful entities in the input text.
    *   **Entity Details:** For each identified entity, extract the following information:
        *   `entity_name`: The name of the entity. If the entity name is case-insensitive, capitalize the first letter of each significant word (title case). Ensure **consistent naming** across the entire extraction process.
        *   `entity_type`: Categorize the entity using one of the following types: `{entity_types}`. If none of the provided entity types apply, do not add new entity type and classify it as `Other`.
        *   `entity_description`: Provide a concise yet comprehensive description of the entity's attributes and activities, based *solely* on the information present in the input text.
    *   **Output Format - Entities:** Output a total of 4 fields for each entity, delimited by `{tuple_delimiter}`, on a single line. The first field *must* be the literal string `entity`.
        *   Format: `entity{tuple_delimiter}entity_name{tuple_delimiter}entity_type{tuple_delimiter}entity_description`

2.  **Relationship Extraction & Output:**
    *   **Identification:** Identify direct, clearly stated, and meaningful relationships between previously extracted entities.
    *   **N-ary Relationship Decomposition:** If a single statement describes a relationship involving more than two entities (an N-ary relationship), decompose it into multiple binary (two-entity) relationship pairs for separate description.
    *   **Relationship Details:** For each binary relationship, extract the following fields:
        *   `source_entity`: The name of the source entity. Ensure **consistent naming** with entity extraction.
        *   `target_entity`: The name of the target entity. Ensure **consistent naming** with entity extraction.
        *   `relationship_keywords`: One or more high-level keywords summarizing the overarching nature, concepts, or themes of the relationship. Multiple keywords within this field must be separated by a comma `,`.
        *   `relationship_description`: A concise explanation of the nature of the relationship between the source and target entities.
    *   **Output Format - Relationships:** Output a total of 5 fields for each relationship, delimited by `{tuple_delimiter}`, on a single line. The first field *must* be the literal string `relation`.
        *   Format: `relation{tuple_delimiter}source_entity{tuple_delimiter}target_entity{tuple_delimiter}relationship_keywords{tuple_delimiter}relationship_description`

3.  **Delimiter Usage Protocol:**
    *   The `{tuple_delimiter}` is a complete, atomic marker and **must not be filled with content**. It serves strictly as a field separator.

4.  **Relationship Direction & Duplication:**
    *   Treat all relationships as **undirected** unless explicitly stated otherwise.
    *   Avoid outputting duplicate relationships.

5.  **Output Order:**
    *   Output all extracted entities first, followed by all extracted relationships.

6.  **Context & Objectivity:**
    *   Ensure all entity names and descriptions are written in the **third person**.
    *   Explicitly name the subject or object; **avoid using pronouns** such as `this article`, `this paper`, `our company`, `I`, `you`, and `he/she`.

7.  **Language:**
    *   The entire output (entity names, keywords, and descriptions) must be written in `{language}`.
    *   Proper nouns (e.g., personal names, place names, organization names) should be retained in their original language if a proper translation is not available.

8.  **Completion Signal:** Output the literal string `{completion_delimiter}` only after all entities and relationships have been completely extracted.
"""

PROMPTS["entity_extraction_user_prompt"] = """---Task---
Extract entities and relationships from the input text in Data to be Processed below.

---Instructions---
1.  **Strict Adherence to Format:** Strictly adhere to all format requirements for entity and relationship lists.
2.  **Output Content Only:** Output *only* the extracted list of entities and relationships. Do not include any introductory or concluding remarks.
3.  **Completion Signal:** Output `{completion_delimiter}` as the final line after all relevant entities and relationships have been extracted.
4.  **Output Language:** Ensure the output language is {language}. Proper nouns must be kept in their original language.

---Data to be Processed---
<Entity_types>
[{entity_types}]

<Input Text>
```
{input_text}
```

<Output>
"""

PROMPTS["entity_continue_extraction_user_prompt"] = """---Task---
Based on the last extraction task, identify and extract any **missed or incorrectly formatted** entities and relationships from the input text.

---Instructions---
1.  **Strict Adherence to System Format:** Strictly adhere to all format requirements.
2.  **Focus on Corrections/Additions:**
    *   **Do NOT** re-output entities and relationships that were **correctly and fully** extracted.
    *   If an entity or relationship was **missed** in the last task, extract and output it now.
    *   If an entity or relationship was **incorrectly formatted**, re-output the corrected version.
3.  **Output Content Only:** Output *only* the extracted list.
4.  **Completion Signal:** Output `{completion_delimiter}` as the final line.

<Output>
"""


def get_entity_types(language: str = "Chinese") -> list[str]:
    """Get entity types based on language"""
    if language.lower() in ["chinese", "中文", "zh"]:
        return DEFAULT_ENTITY_TYPES_CN
    return DEFAULT_ENTITY_TYPES_EN


def format_system_prompt(
    entity_types: list[str],
    tuple_delimiter: str = PROMPTS["DEFAULT_TUPLE_DELIMITER"],
    completion_delimiter: str = PROMPTS["DEFAULT_COMPLETION_DELIMITER"],
    language: str = "Chinese"
) -> str:
    """Format system prompt with entity types"""
    return PROMPTS["entity_extraction_system_prompt"].format(
        entity_types=", ".join(entity_types),
        tuple_delimiter=tuple_delimiter,
        completion_delimiter=completion_delimiter,
        language=language
    )


def format_user_prompt(
    input_text: str,
    entity_types: list[str],
    tuple_delimiter: str = PROMPTS["DEFAULT_TUPLE_DELIMITER"],
    completion_delimiter: str = PROMPTS["DEFAULT_COMPLETION_DELIMITER"],
    language: str = "Chinese"
) -> str:
    """Format user prompt with input text"""
    return PROMPTS["entity_extraction_user_prompt"].format(
        entity_types=", ".join(entity_types),
        input_text=input_text,
        tuple_delimiter=tuple_delimiter,
        completion_delimiter=completion_delimiter,
        language=language
    )


def format_continue_prompt(
    input_text: str,
    tuple_delimiter: str = PROMPTS["DEFAULT_TUPLE_DELIMITER"],
    completion_delimiter: str = PROMPTS["DEFAULT_COMPLETION_DELIMITER"],
    language: str = "Chinese"
) -> str:
    """Format continue extraction prompt"""
    return PROMPTS["entity_continue_extraction_user_prompt"].format(
        input_text=input_text,
        tuple_delimiter=tuple_delimiter,
        completion_delimiter=completion_delimiter,
        language=language
    )