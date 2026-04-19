# 模型管理路由
import logging
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel

from ...core.database import get_db
from ...models import Model

router = APIRouter()
logger = logging.getLogger(__name__)


def mask_api_key(api_key: Optional[str]) -> Optional[str]:
    """掩码 API key，显示前缀和后缀"""
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "***"
    return f"{api_key[:4]}***{api_key[-4:]}"


# Pydantic Schemas
class ModelCreate(BaseModel):
    name: str
    model_type: str  # llm/embedding/reranker
    provider: Optional[str] = None
    model_name: Optional[str] = None
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 2048
    is_default: bool = False
    dimension: Optional[int] = None
    max_input_length: Optional[int] = None


class ModelResponse(BaseModel):
    id: UUID
    name: str
    model_type: str
    provider: Optional[str]
    model_name: Optional[str]
    endpoint: Optional[str]
    api_key_masked: Optional[str] = None  # 掩码显示，如 "sk-***...***abc"
    params: Optional[dict]
    is_default: bool
    status: str
    dimension: Optional[int]
    max_input_length: Optional[int]

    class Config:
        from_attributes = True


class ModelTestRequest(BaseModel):
    test_prompt: Optional[str] = "Hello, this is a test."


def model_to_response(model: Model) -> dict:
    """将 Model 转换为响应字典，添加掩码的 API key"""
    return {
        "id": model.id,
        "name": model.name,
        "model_type": model.model_type,
        "provider": model.provider,
        "model_name": model.model_name,
        "endpoint": model.endpoint,
        "api_key_masked": mask_api_key(model.api_key_encrypted),
        "params": model.params,
        "is_default": model.is_default,
        "status": model.status,
        "dimension": model.dimension,
        "max_input_length": model.max_input_length,
    }


@router.post("", response_model=ModelResponse)
async def create_model(
    data: ModelCreate,
    db: AsyncSession = Depends(get_db)
):
    """创建模型配置"""
    params = {
        "temperature": data.temperature,
        "max_tokens": data.max_tokens
    }
    model = Model(
        name=data.name,
        model_type=data.model_type,
        provider=data.provider,
        model_name=data.model_name,
        endpoint=data.endpoint,
        api_key_encrypted=data.api_key,
        params=params,
        is_default=data.is_default,
        dimension=data.dimension,
        max_input_length=data.max_input_length,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model_to_response(model)


@router.get("", response_model=List[ModelResponse])
async def list_models(
    type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取模型列表"""
    query = select(Model)
    if type:
        query = query.where(Model.model_type == type)
    result = await db.execute(query)
    models = result.scalars().all()
    return [model_to_response(m) for m in models]


@router.get("/{model_id}", response_model=ModelResponse)
async def get_model(
    model_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取模型详情"""
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")
    return model_to_response(model)


@router.put("/{model_id}", response_model=ModelResponse)
async def update_model(
    model_id: UUID,
    data: ModelCreate,
    db: AsyncSession = Depends(get_db)
):
    """更新模型配置"""
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")

    model.name = data.name
    model.model_type = data.model_type
    model.provider = data.provider
    model.model_name = data.model_name
    model.endpoint = data.endpoint
    # 只有传入了新的 api_key 才更新
    if data.api_key:
        model.api_key_encrypted = data.api_key
    model.params = {
        "temperature": data.temperature,
        "max_tokens": data.max_tokens
    }
    model.is_default = data.is_default
    model.dimension = data.dimension
    model.max_input_length = data.max_input_length

    await db.commit()
    await db.refresh(model)
    return model_to_response(model)


@router.delete("/{model_id}")
async def delete_model(
    model_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除模型配置"""
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")

    await db.delete(model)
    await db.commit()
    return {"message": "删除成功"}


@router.post("/{model_id}/test")
async def test_model(
    model_id: UUID,
    db: AsyncSession = Depends(get_db),
    data: Optional[ModelTestRequest] = Body(default=None)
):
    """测试模型连接"""
    logger.info(f"开始测试模型 {model_id}")
    test_prompt = data.test_prompt if data else "Hello, this is a test."

    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        logger.warning(f"模型 {model_id} 不存在")
        raise HTTPException(status_code=404, detail="模型不存在")

    logger.info(f"模型信息: name={model.name}, type={model.model_type}, provider={model.provider}, endpoint={model.endpoint}")

    try:
        import httpx

        params = model.params or {}
        provider = model.provider or "openai"

        # 根据供应商构建请求
        if model.model_type == "llm":
            request_data = _build_llm_test_request(provider, model, test_prompt, params)
            logger.info(f"LLM测试请求: url={request_data['url']}")
        elif model.model_type == "embedding":
            request_data = _build_embedding_test_request(provider, model, test_prompt)
            logger.info(f"Embedding测试请求: url={request_data['url']}")
        else:
            logger.info(f"非LLM/Embedding模型，直接返回成功")
            return {
                "success": True,
                "message": "配置验证通过",
                "model_id": str(model_id)
            }

        logger.info(f"发送请求到 {request_data['url']}...")
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                request_data["url"],
                headers=request_data["headers"],
                json=request_data["body"]
            )
            logger.info(f"收到响应: status={response.status_code}")
            if response.status_code != 200:
                logger.error(f"API返回错误: {response.status_code} - {response.text[:200]}")
                return {
                    "success": False,
                    "error": f"API返回错误: {response.status_code} - {response.text[:200]}",
                    "model_id": str(model_id)
                }
            logger.info(f"模型 {model_id} 测试成功")
            return {
                "success": True,
                "message": "模型连接测试成功",
                "model_id": str(model_id)
            }

    except httpx.ConnectError as e:
        logger.error(f"无法连接到API地址: {str(e)}")
        return {
            "success": False,
            "error": f"无法连接到API地址: {str(e)}",
            "model_id": str(model_id)
        }
    except httpx.TimeoutException:
        logger.error(f"连接超时: {request_data.get('url', 'unknown')}")
        return {
            "success": False,
            "error": "连接超时，请检查API地址是否正确",
            "model_id": str(model_id)
        }
    except Exception as e:
        logger.error(f"测试模型 {model_id} 异常: {type(e).__name__}: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "model_id": str(model_id)
        }


def _build_llm_test_request(provider: str, model, test_prompt: str, params: dict) -> dict:
    """构建 LLM 测试请求"""
    model_name = model.model_name or model.name
    api_key = model.api_key_encrypted
    endpoint = model.endpoint

    if provider == "azure":
        # Azure OpenAI 使用 api-key header 和 deployments 路径
        return {
            "url": f"{endpoint}/deployments/{model_name}/chat/completions?api-version=2024-02-01",
            "headers": {
                "api-key": api_key,
                "Content-Type": "application/json"
            },
            "body": {
                "messages": [{"role": "user", "content": test_prompt}],
                "max_tokens": params.get("max_tokens", 100),
                "temperature": params.get("temperature", 0.7)
            }
        }
    elif provider == "zhipuai":
        # 智谱AI
        return {
            "url": f"{endpoint}/chat/completions",
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            "body": {
                "model": model_name,
                "messages": [{"role": "user", "content": test_prompt}],
                "max_tokens": params.get("max_tokens", 100),
                "temperature": params.get("temperature", 0.7)
            }
        }
    elif provider == "baidu":
        # 百度千帆 - 需要先获取 access_token
        return {
            "url": f"{endpoint}/chat/completions",
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            "body": {
                "model": model_name,
                "messages": [{"role": "user", "content": test_prompt}],
                "max_tokens": params.get("max_tokens", 100),
                "temperature": params.get("temperature", 0.7)
            }
        }
    elif provider == "aliyun":
        # 阿里云百炼
        return {
            "url": f"{endpoint}/chat/completions",
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            "body": {
                "model": model_name,
                "messages": [{"role": "user", "content": test_prompt}],
                "max_tokens": params.get("max_tokens", 100),
                "temperature": params.get("temperature", 0.7)
            }
        }
    elif provider == "volcengine":
        # 火山引擎
        return {
            "url": f"{endpoint}/chat/completions",
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            "body": {
                "model": model_name,
                "messages": [{"role": "user", "content": test_prompt}],
                "max_tokens": params.get("max_tokens", 100),
                "temperature": params.get("temperature", 0.7)
            }
        }
    else:
        # OpenAI 及兼容格式 (默认)
        return {
            "url": f"{endpoint}/chat/completions",
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            "body": {
                "model": model_name,
                "messages": [{"role": "user", "content": test_prompt}],
                "max_tokens": params.get("max_tokens", 100),
                "temperature": params.get("temperature", 0.7)
            }
        }


def _build_embedding_test_request(provider: str, model, test_prompt: str) -> dict:
    """构建 Embedding 测试请求"""
    model_name = model.model_name or model.name
    api_key = model.api_key_encrypted
    endpoint = model.endpoint

    if provider == "azure":
        return {
            "url": f"{endpoint}/deployments/{model_name}/embeddings?api-version=2024-02-01",
            "headers": {
                "api-key": api_key,
                "Content-Type": "application/json"
            },
            "body": {
                "input": test_prompt
            }
        }
    else:
        # OpenAI 及兼容格式
        return {
            "url": f"{endpoint}/embeddings",
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            "body": {
                "model": model_name,
                "input": test_prompt
            }
        }