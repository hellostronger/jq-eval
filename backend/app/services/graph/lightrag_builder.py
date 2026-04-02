# LightRAG Graph Builder Implementation
import httpx
import time
import re
import asyncio
from typing import List, Dict, Any, Optional, Callable
from collections import defaultdict

from .base import BaseGraphBuilder
from .models import (
    GraphEntity,
    GraphRelation,
    KnowledgeGraphResult,
    GraphBuildRequest,
    GraphChunkBuildRequest,
    GraphBuildResult,
    EntityExtractRequest,
    EntityExtractResult,
    RelationExtractRequest,
    RelationExtractResult,
)
from .prompts import (
    PROMPTS,
    get_entity_types,
    format_system_prompt,
    format_user_prompt,
)


class LightRAGGraphBuilder(BaseGraphBuilder):
    """LightRAG 图谱构建器实现"""

    builder_type = "lightrag"
    display_name = "LightRAG"
    description = "基于 LightRAG 的知识图谱构建，支持实体抽取、关系抽取和多模式检索"

    def __init__(
        self,
        llm_config: Dict[str, Any],
        embedding_func: Optional[Callable] = None,
    ):
        """
        Args:
            llm_config: LLM 配置，包含:
                - api_url: API 地址 (OpenAI兼容)
                - api_key: API 密钥
                - model: 模型名称
                - max_tokens: 最大输出token
                - temperature: 温度参数
            embedding_func: 可选的embedding函数
        """
        self.llm_config = llm_config
        self.embedding_func = embedding_func

        # Default LLM config
        self.api_url = llm_config.get("api_url", "").rstrip("/")
        self.api_key = llm_config.get("api_key", "")
        self.model = llm_config.get("model", "gpt-4o-mini")
        self.max_tokens = llm_config.get("max_tokens", 4000)
        self.temperature = llm_config.get("temperature", 0.1)

    async def _call_llm(
        self,
        user_prompt: str,
        system_prompt: str,
        max_tokens: Optional[int] = None,
    ) -> tuple[str, float]:
        """调用LLM API

        Returns:
            tuple: (response_text, response_time)
        """
        start_time = time.time()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": self.temperature,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            response_time = time.time() - start_time
            return content, response_time

        except Exception as e:
            response_time = time.time() - start_time
            raise RuntimeError(f"LLM API call failed: {str(e)}")

    def _chunk_text(
        self,
        text: str,
        chunk_size: int = 1200,
        chunk_overlap: int = 100,
    ) -> List[str]:
        """简单文本分块（按字符数）

        Args:
            text: 输入文本
            chunk_size: 分块大小（字符）
            chunk_overlap: 重叠大小

        Returns:
            分块列表
        """
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            chunks.append(chunk.strip())
            start = end - chunk_overlap

        return chunks

    def _parse_extraction_result(
        self,
        result: str,
        chunk_id: str = "chunk-0",
        tuple_delimiter: str = PROMPTS["DEFAULT_TUPLE_DELIMITER"],
        completion_delimiter: str = PROMPTS["DEFAULT_COMPLETION_DELIMITER"],
    ) -> tuple[Dict[str, List], Dict[str, List]]:
        """解析LLM抽取结果

        Returns:
            tuple: (entities_dict, relations_dict)
        """
        entities_dict = defaultdict(list)
        relations_dict = defaultdict(list)

        # Split by completion delimiter and newline
        records = re.split(rf"[\n]|{completion_delimiter}|{completion_delimiter.lower()}", result)

        for record in records:
            record = record.strip()
            if not record:
                continue

            # Fix format errors
            if not record.startswith("entity") and not record.startswith("relation"):
                # Try to fix incomplete records
                if tuple_delimiter in record:
                    record = f"entity{tuple_delimiter}{record}"

            # Parse entity records
            if record.startswith("entity"):
                parts = record.split(tuple_delimiter)
                if len(parts) >= 4:
                    entity_name = parts[1].strip()
                    entity_type = parts[2].strip()
                    entity_description = parts[3].strip()
                    entities_dict[entity_name].append({
                        "entity_type": entity_type,
                        "description": entity_description,
                        "source_id": chunk_id,
                    })

            # Parse relation records
            elif record.startswith("relation"):
                parts = record.split(tuple_delimiter)
                if len(parts) >= 5:
                    source_entity = parts[1].strip()
                    target_entity = parts[2].strip()
                    keywords = parts[3].strip()
                    description = parts[4].strip()
                    relations_dict[f"{source_entity}-{target_entity}"].append({
                        "keywords": keywords,
                        "description": description,
                        "source_id": chunk_id,
                        "weight": 1.0,
                    })

        return dict(entities_dict), dict(relations_dict)

    def _merge_entities(
        self,
        entities_dict: Dict[str, List],
    ) -> List[GraphEntity]:
        """合并同名实体的多个描述"""
        merged = []
        for entity_name, descriptions in entities_dict.items():
            # Merge descriptions
            all_descriptions = [d["description"] for d in descriptions]
            merged_description = "; ".join(all_descriptions[:3])  # 取前3个描述

            # Use first entity type
            entity_type = descriptions[0].get("entity_type", "Other")

            # Collect source_ids
            source_ids = [d.get("source_id") for d in descriptions if d.get("source_id")]

            merged.append(GraphEntity(
                name=entity_name,
                entity_type=entity_type,
                description=merged_description,
                source_id=source_ids[0] if source_ids else None,
                properties={"source_ids": source_ids, "count": len(descriptions)},
            ))

        return merged

    def _merge_relations(
        self,
        relations_dict: Dict[str, List],
    ) -> List[GraphRelation]:
        """合并同名关系的多个描述"""
        merged = []
        for relation_key, descriptions in relations_dict.items():
            parts = relation_key.split("-")
            if len(parts) != 2:
                continue

            source_entity, target_entity = parts[0], parts[1]

            # Merge descriptions
            all_descriptions = [d["description"] for d in descriptions]
            merged_description = "; ".join(all_descriptions[:3])

            # Use first keywords
            keywords = descriptions[0].get("keywords", "")

            # Sum weights
            total_weight = sum(d.get("weight", 1.0) for d in descriptions)

            # Collect source_ids
            source_ids = [d.get("source_id") for d in descriptions if d.get("source_id")]

            merged.append(GraphRelation(
                source_entity=source_entity,
                target_entity=target_entity,
                description=merged_description,
                keywords=keywords,
                weight=total_weight,
                source_id=source_ids[0] if source_ids else None,
                properties={"source_ids": source_ids, "count": len(descriptions)},
            ))

        return merged

    async def build_from_chunks(
        self,
        request: GraphChunkBuildRequest,
    ) -> GraphBuildResult:
        """从已分片的文本列表构建图谱"""
        start_time = time.time()

        try:
            chunks = request.chunks
            entity_types = request.entity_types or get_entity_types(request.language)

            all_entities_dict: Dict[str, List] = defaultdict(list)
            all_relations_dict: Dict[str, List] = defaultdict(list)

            # Process each chunk
            system_prompt = format_system_prompt(
                entity_types=entity_types,
                language=request.language,
            )

            # Process chunks in parallel (limit concurrency)
            semaphore = asyncio.Semaphore(3)  # Max 3 concurrent LLM calls

            async def process_chunk(chunk: str, idx: int):
                async with semaphore:
                    chunk_id = f"chunk-{idx}"
                    user_prompt = format_user_prompt(
                        input_text=chunk,
                        entity_types=entity_types,
                        language=request.language,
                    )

                    result, _ = await self._call_llm(user_prompt, system_prompt)
                    entities_dict, relations_dict = self._parse_extraction_result(
                        result, chunk_id
                    )
                    return entities_dict, relations_dict

            # Run all chunks
            results = await asyncio.gather(*[
                process_chunk(chunk, idx) for idx, chunk in enumerate(chunks)
            ])

            # Merge all results
            for entities_dict, relations_dict in results:
                for entity_name, data_list in entities_dict.items():
                    all_entities_dict[entity_name].extend(data_list)
                for relation_key, data_list in relations_dict.items():
                    all_relations_dict[relation_key].extend(data_list)

            # Create final graph
            entities = self._merge_entities(dict(all_entities_dict))
            relations = self._merge_relations(dict(all_relations_dict))

            graph = KnowledgeGraphResult(
                entities=entities,
                relations=relations,
                metadata={
                    "doc_id": request.doc_id,
                    "chunk_count": len(chunks),
                    "builder_type": self.builder_type,
                },
            )

            processing_time = time.time() - start_time

            return GraphBuildResult(
                success=True,
                graph=graph,
                processing_time=processing_time,
                chunk_count=len(chunks),
                entity_count=len(entities),
                relation_count=len(relations),
            )

        except Exception as e:
            processing_time = time.time() - start_time
            return GraphBuildResult(
                success=False,
                error=str(e),
                processing_time=processing_time,
            )

    async def build_from_document(
        self,
        request: GraphBuildRequest,
    ) -> GraphBuildResult:
        """从完整文档构建图谱（先分片再抽取）"""
        start_time = time.time()

        try:
            # Chunk the document
            chunks = self._chunk_text(
                request.text,
                chunk_size=request.chunk_size,
                chunk_overlap=request.chunk_overlap,
            )

            # Build from chunks
            chunk_request = GraphChunkBuildRequest(
                chunks=chunks,
                doc_id=request.doc_id,
                entity_types=request.entity_types,
                language=request.language,
                options=request.options,
            )

            result = await self.build_from_chunks(chunk_request)

            # Update metadata
            if result.graph:
                result.graph.metadata["chunk_size"] = request.chunk_size
                result.graph.metadata["chunk_overlap"] = request.chunk_overlap
                result.graph.metadata["original_text_length"] = len(request.text)

            return result

        except Exception as e:
            processing_time = time.time() - start_time
            return GraphBuildResult(
                success=False,
                error=str(e),
                processing_time=processing_time,
            )

    async def extract_entities(
        self,
        request: EntityExtractRequest,
    ) -> EntityExtractResult:
        """从单个文本抽取实体"""
        start_time = time.time()

        try:
            entity_types = request.entity_types or get_entity_types(request.language)

            system_prompt = format_system_prompt(
                entity_types=entity_types,
                language=request.language,
            )
            user_prompt = format_user_prompt(
                input_text=request.text,
                entity_types=entity_types,
                language=request.language,
            )

            result, _ = await self._call_llm(user_prompt, system_prompt)
            entities_dict, _ = self._parse_extraction_result(result)

            entities = self._merge_entities(entities_dict)

            processing_time = time.time() - start_time

            return EntityExtractResult(
                success=True,
                entities=entities,
                processing_time=processing_time,
            )

        except Exception as e:
            processing_time = time.time() - start_time
            return EntityExtractResult(
                success=False,
                error=str(e),
                processing_time=processing_time,
            )

    async def extract_relations(
        self,
        request: RelationExtractRequest,
    ) -> RelationExtractResult:
        """从文本抽取关系"""
        start_time = time.time()

        try:
            entity_types = get_entity_types(request.language)

            # Include known entities in the prompt for context
            entities_context = ", ".join(request.entities) if request.entities else ""

            system_prompt = format_system_prompt(
                entity_types=entity_types,
                language=request.language,
            )
            user_prompt = format_user_prompt(
                input_text=request.text,
                entity_types=entity_types,
                language=request.language,
            )

            # Add entities hint
            if entities_context:
                user_prompt += f"\n\n已知实体列表: {entities_context}\n请重点抽取这些实体之间的关系。"

            result, _ = await self._call_llm(user_prompt, system_prompt)
            _, relations_dict = self._parse_extraction_result(result)

            # Filter relations to only include known entities
            if request.entities:
                filtered_relations = {}
                for key, data in relations_dict.items():
                    parts = key.split("-")
                    if len(parts) == 2:
                        src, tgt = parts[0], parts[1]
                        if src in request.entities or tgt in request.entities:
                            filtered_relations[key] = data
                relations_dict = filtered_relations

            relations = self._merge_relations(relations_dict)

            processing_time = time.time() - start_time

            return RelationExtractResult(
                success=True,
                relations=relations,
                processing_time=processing_time,
            )

        except Exception as e:
            processing_time = time.time() - start_time
            return RelationExtractResult(
                success=False,
                error=str(e),
                processing_time=processing_time,
            )

    async def health_check(self) -> bool:
        """检查LLM API连接"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.api_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return response.status_code == 200
        except:
            return False