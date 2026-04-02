# Graph Building API Routes
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import JSONResponse
from typing import List, Optional, Dict, Any
import tempfile
import os

from ...services.graph import (
    BaseGraphBuilder,
    LightRAGGraphBuilder,
    GraphBuildRequest,
    GraphChunkBuildRequest,
    GraphBuildResult,
    EntityExtractRequest,
    EntityExtractResult,
    RelationExtractRequest,
    RelationExtractResult,
    GraphBuilderInfo,
)
from ...core.config import settings
from ...models.model import Model
from ...core.database import AsyncSessionLocal

router = APIRouter(prefix="/graph", tags=["Graph Building"])

# Graph builder registry (can be extended)
_BUILDER_REGISTRY: Dict[str, type] = {
    "lightrag": LightRAGGraphBuilder,
}


async def get_graph_builder(builder_type: str = "lightrag") -> BaseGraphBuilder:
    """Get graph builder instance with LLM config from database"""
    if builder_type not in _BUILDER_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown builder type: {builder_type}. Available: {list(_BUILDER_REGISTRY.keys())}"
        )

    # Get default LLM config from database
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(Model).where(
                Model.model_type == "llm",
                Model.is_default == True,
                Model.status == "active"
            )
        )
        default_model = result.scalar_one_or_none()

        if default_model:
            llm_config = {
                "api_url": default_model.endpoint or "https://api.openai.com/v1",
                "api_key": default_model.api_key_encrypted or "",
                "model": default_model.name,
                "max_tokens": default_model.params.get("max_tokens", 4000),
                "temperature": default_model.params.get("temperature", 0.1),
            }
        else:
            # Fallback to default OpenAI config
            llm_config = {
                "api_url": "https://api.openai.com/v1",
                "api_key": os.getenv("OPENAI_API_KEY", ""),
                "model": "gpt-4o-mini",
                "max_tokens": 4000,
                "temperature": 0.1,
            }

    builder_class = _BUILDER_REGISTRY[builder_type]
    return builder_class(llm_config=llm_config)


# ========== Builder Info API ==========

@router.get("/builders", response_model=List[GraphBuilderInfo])
async def list_graph_builders():
    """List available graph builders"""
    builders = []
    for builder_type, builder_class in _BUILDER_REGISTRY.items():
        # Create dummy instance to get info
        dummy = builder_class(llm_config={})
        builders.append(GraphBuilderInfo(
            builder_type=builder_type,
            display_name=dummy.display_name,
            description=dummy.description,
        ))
    return builders


@router.get("/builders/{builder_type}")
async def get_builder_info(builder_type: str):
    """Get specific builder info"""
    if builder_type not in _BUILDER_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Builder not found: {builder_type}")

    builder = await get_graph_builder(builder_type)
    return builder.get_info()


# ========== Chunk Mode API ==========

@router.post("/build/chunks", response_model=GraphBuildResult)
async def build_from_chunks(
    chunks: List[str],
    doc_id: Optional[str] = None,
    builder_type: str = "lightrag",
    entity_types: Optional[List[str]] = None,
    language: str = "Chinese",
):
    """Build knowledge graph from pre-chunked text list

    Args:
        chunks: List of pre-chunked text segments
        doc_id: Optional document ID for tracking
        builder_type: Type of graph builder (default: lightrag)
        entity_types: Custom entity types to extract
        language: Output language (Chinese/English)

    Returns:
        GraphBuildResult with extracted entities and relations
    """
    builder = await get_graph_builder(builder_type)

    request = GraphChunkBuildRequest(
        chunks=chunks,
        doc_id=doc_id,
        entity_types=entity_types,
        language=language,
    )

    result = await builder.build_from_chunks(request)
    return result


# ========== Document Mode API ==========

@router.post("/build/document", response_model=GraphBuildResult)
async def build_from_document(
    text: str,
    doc_id: Optional[str] = None,
    builder_type: str = "lightrag",
    entity_types: Optional[List[str]] = None,
    language: str = "Chinese",
    chunk_size: int = 1200,
    chunk_overlap: int = 100,
):
    """Build knowledge graph from complete document

    Args:
        text: Complete document text
        doc_id: Optional document ID
        builder_type: Type of graph builder
        entity_types: Custom entity types
        language: Output language
        chunk_size: Chunk size in characters
        chunk_overlap: Overlap between chunks

    Returns:
        GraphBuildResult with extracted entities and relations
    """
    builder = await get_graph_builder(builder_type)

    request = GraphBuildRequest(
        text=text,
        doc_id=doc_id,
        entity_types=entity_types,
        language=language,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    result = await builder.build_from_document(request)
    return result


@router.post("/build/file", response_model=GraphBuildResult)
async def build_from_file(
    file: UploadFile = File(...),
    builder_type: str = "lightrag",
    entity_types: Optional[List[str]] = None,
    language: str = "Chinese",
    chunk_size: int = 1200,
    chunk_overlap: int = 100,
):
    """Build knowledge graph from uploaded file

    Supports: .txt, .md, .pdf (if text extractable)

    Args:
        file: Uploaded file
        builder_type: Type of graph builder
        entity_types: Custom entity types
        language: Output language
        chunk_size: Chunk size
        chunk_overlap: Chunk overlap

    Returns:
        GraphBuildResult with extracted entities and relations
    """
    # Read file content
    content = await file.read()
    filename = file.filename or "unknown"

    # Decode text
    try:
        if filename.endswith(".pdf"):
            # PDF extraction would require pdfplumber or similar
            raise HTTPException(
                status_code=400,
                detail="PDF extraction not supported yet. Please use .txt or .md files."
            )
        else:
            # Plain text
            text = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = content.decode("gbk")
        except:
            raise HTTPException(status_code=400, detail="Cannot decode file content")

    builder = await get_graph_builder(builder_type)

    request = GraphBuildRequest(
        text=text,
        doc_id=filename,
        entity_types=entity_types,
        language=language,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    result = await builder.build_from_document(request)

    # Add filename to metadata
    if result.graph:
        result.graph.metadata["filename"] = filename

    return result


# ========== Entity Extraction API ==========

@router.post("/extract/entities", response_model=EntityExtractResult)
async def extract_entities(
    text: str,
    entity_types: Optional[List[str]] = None,
    language: str = "Chinese",
    builder_type: str = "lightrag",
):
    """Extract entities from text

    Args:
        text: Input text
        entity_types: Custom entity types
        language: Output language
        builder_type: Graph builder type

    Returns:
        EntityExtractResult with extracted entities
    """
    builder = await get_graph_builder(builder_type)

    request = EntityExtractRequest(
        text=text,
        entity_types=entity_types,
        language=language,
    )

    result = await builder.extract_entities(request)
    return result


# ========== Relation Extraction API ==========

@router.post("/extract/relations", response_model=RelationExtractResult)
async def extract_relations(
    text: str,
    entities: List[str] = [],
    language: str = "Chinese",
    builder_type: str = "lightrag",
):
    """Extract relations from text

    Args:
        text: Input text
        entities: Known entity names to focus on
        language: Output language
        builder_type: Graph builder type

    Returns:
        RelationExtractResult with extracted relations
    """
    builder = await get_graph_builder(builder_type)

    request = RelationExtractRequest(
        text=text,
        entities=entities,
        language=language,
    )

    result = await builder.extract_relations(request)
    return result


# ========== Health Check ==========

@router.get("/health/{builder_type}")
async def builder_health_check(builder_type: str):
    """Check graph builder health"""
    try:
        builder = await get_graph_builder(builder_type)
        healthy = await builder.health_check()
        return {
            "builder_type": builder_type,
            "status": "healthy" if healthy else "unhealthy",
        }
    except HTTPException:
        raise
    except Exception as e:
        return {
            "builder_type": builder_type,
            "status": "unhealthy",
            "error": str(e),
        }