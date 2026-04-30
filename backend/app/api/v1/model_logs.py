# 模型日志管理路由
import logging
import time
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
from datetime import datetime

from ...core.database import get_db
from ...models import Model, ModelRequestLog
from ...services.llm.llm_client import create_llm_from_config

router = APIRouter()
logger = logging.getLogger(__name__)


# Pydantic Schemas
class LogResponse(BaseModel):
    id: UUID
    model_id: UUID
    model_name: Optional[str] = None
    session_id: Optional[UUID]
    request_type: str
    prompt: str
    system_prompt: Optional[str]
    params: Optional[dict]
    response: Optional[str]
    response_metadata: Optional[dict]
    status: str
    error_message: Optional[str]
    latency_ms: Optional[int]
    is_replay: bool
    replay_from_log_id: Optional[UUID]
    replay_model_id: Optional[UUID]
    created_at: datetime

    class Config:
        from_attributes = True


class LogListResponse(BaseModel):
    items: List[LogResponse]
    total: int


class ReplayRequest(BaseModel):
    target_model_id: UUID


class BatchReplayRequest(BaseModel):
    log_ids: List[UUID]
    target_model_ids: List[UUID]


class MultiModelCompareRequest(BaseModel):
    log_id: UUID
    target_model_ids: List[UUID]


class ReplayResult(BaseModel):
    log_id: UUID
    original_response: Optional[str]
    original_model_id: UUID
    original_model_name: Optional[str]
    replay_model_id: UUID
    replay_model_name: Optional[str]
    replay_response: Optional[str]
    replay_latency_ms: Optional[int]
    replay_status: str
    replay_error: Optional[str]
    comparison: Optional[dict] = None


class MultiModelCompareResult(BaseModel):
    log_id: UUID
    original_prompt: str
    original_response: Optional[str]
    original_model_name: Optional[str]
    results: List[ReplayResult]


class LogStatsResponse(BaseModel):
    total_logs: int
    logs_by_model: dict
    logs_by_type: dict
    logs_by_status: dict
    avg_latency_ms: Optional[float]
    replay_count: int


def log_to_response(log: ModelRequestLog, model_name: Optional[str] = None) -> dict:
    """将日志转换为响应字典"""
    return {
        "id": log.id,
        "model_id": log.model_id,
        "model_name": model_name,
        "session_id": log.session_id,
        "request_type": log.request_type,
        "prompt": log.prompt,
        "system_prompt": log.system_prompt,
        "params": log.params,
        "response": log.response,
        "response_metadata": log.response_metadata,
        "status": log.status,
        "error_message": log.error_message,
        "latency_ms": log.latency_ms,
        "is_replay": log.is_replay,
        "replay_from_log_id": log.replay_from_log_id,
        "replay_model_id": log.replay_model_id,
        "created_at": log.created_at,
    }


@router.get("", response_model=LogListResponse)
async def list_logs(
    model_id: Optional[UUID] = None,
    request_type: Optional[str] = None,
    status: Optional[str] = None,
    is_replay: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """获取日志列表"""
    query = select(ModelRequestLog)

    if model_id:
        query = query.where(ModelRequestLog.model_id == model_id)
    if request_type:
        query = query.where(ModelRequestLog.request_type == request_type)
    if status:
        query = query.where(ModelRequestLog.status == status)
    if is_replay is not None:
        query = query.where(ModelRequestLog.is_replay == is_replay)

    # 获取总数
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # 分页查询
    query = query.order_by(desc(ModelRequestLog.created_at)).offset(skip).limit(limit)
    result = await db.execute(query)
    logs = result.scalars().all()

    # 获取模型名称
    model_names = {}
    if logs:
        model_ids = [log.model_id for log in logs]
        model_result = await db.execute(
            select(Model.id, Model.name).where(Model.id.in_(model_ids))
        )
        for row in model_result:
            model_names[row[0]] = row[1]

    items = [log_to_response(log, model_names.get(log.model_id)) for log in logs]
    return {"items": items, "total": total}


@router.get("/{log_id}", response_model=LogResponse)
async def get_log(
    log_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取单条日志详情"""
    result = await db.execute(
        select(ModelRequestLog).where(ModelRequestLog.id == log_id)
    )
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")

    # 获取模型名称
    model_result = await db.execute(
        select(Model.name).where(Model.id == log.model_id)
    )
    model_name = model_result.scalar_one_or_none()

    return log_to_response(log, model_name)


@router.post("/{log_id}/replay", response_model=ReplayResult)
async def replay_log(
    log_id: UUID,
    data: ReplayRequest,
    db: AsyncSession = Depends(get_db)
):
    """单条回放测试"""
    # 获取源日志
    result = await db.execute(
        select(ModelRequestLog).where(ModelRequestLog.id == log_id)
    )
    source_log = result.scalar_one_or_none()
    if not source_log:
        raise HTTPException(status_code=404, detail="日志不存在")

    # 获取目标模型
    model_result = await db.execute(
        select(Model).where(Model.id == data.target_model_id)
    )
    target_model = model_result.scalar_one_or_none()
    if not target_model:
        raise HTTPException(status_code=404, detail="目标模型不存在")

    if target_model.model_type != "llm":
        raise HTTPException(status_code=400, detail="目标模型必须是LLM类型")

    # 获取原始模型名称
    original_model_result = await db.execute(
        select(Model.name).where(Model.id == source_log.model_id)
    )
    original_model_name = original_model_result.scalar_one_or_none()

    # 创建LLM客户端
    llm = await create_llm_from_config(target_model)

    # 构建消息
    from langchain_core.messages import HumanMessage, SystemMessage
    messages = []
    if source_log.system_prompt:
        messages.append(SystemMessage(content=source_log.system_prompt))
    if source_log.messages:
        for msg in source_log.messages:
            if msg.get("role") == "system":
                messages.append(SystemMessage(content=msg.get("content", "")))
            elif msg.get("role") == "human":
                messages.append(HumanMessage(content=msg.get("content", "")))
    else:
        messages.append(HumanMessage(content=source_log.prompt))

    # 执行回放
    start_time = time.time()
    try:
        response = await llm.ainvoke(messages)
        latency_ms = int((time.time() - start_time) * 1000)
        response_content = response.content if hasattr(response, "content") else str(response)
        status = "success"
        error = None

        # 保存回放日志
        replay_log = ModelRequestLog(
            model_id=target_model.id,
            session_id=source_log.session_id,
            request_type=source_log.request_type,
            prompt=source_log.prompt,
            system_prompt=source_log.system_prompt,
            messages=source_log.messages,
            params=source_log.params,
            response=response_content,
            status=status,
            latency_ms=latency_ms,
            is_replay=True,
            replay_from_log_id=log_id,
            replay_model_id=target_model.id,
        )
        db.add(replay_log)
        await db.commit()

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        response_content = None
        status = "failed"
        error = str(e)

    return {
        "log_id": log_id,
        "original_response": source_log.response,
        "original_model_id": source_log.model_id,
        "original_model_name": original_model_name,
        "replay_model_id": target_model.id,
        "replay_model_name": target_model.name,
        "replay_response": response_content,
        "replay_latency_ms": latency_ms,
        "replay_status": status,
        "replay_error": error,
        "comparison": {
            "length_diff": len(response_content or "") - len(source_log.response or "") if response_content else None,
        }
    }


@router.post("/batch-replay", response_model=List[ReplayResult])
async def batch_replay(
    data: BatchReplayRequest,
    db: AsyncSession = Depends(get_db)
):
    """批量回放测试"""
    results = []

    for log_id in data.log_ids:
        for target_model_id in data.target_model_ids:
            try:
                result = await replay_log(
                    log_id=log_id,
                    data=ReplayRequest(target_model_id=target_model_id),
                    db=db
                )
                results.append(result)
            except HTTPException as e:
                results.append({
                    "log_id": log_id,
                    "original_response": None,
                    "original_model_id": None,
                    "original_model_name": None,
                    "replay_model_id": target_model_id,
                    "replay_model_name": None,
                    "replay_response": None,
                    "replay_latency_ms": None,
                    "replay_status": "failed",
                    "replay_error": e.detail,
                })

    return results


@router.post("/multi-model-compare", response_model=MultiModelCompareResult)
async def multi_model_compare(
    data: MultiModelCompareRequest,
    db: AsyncSession = Depends(get_db)
):
    """多模型对比回放"""
    # 获取源日志
    result = await db.execute(
        select(ModelRequestLog).where(ModelRequestLog.id == data.log_id)
    )
    source_log = result.scalar_one_or_none()
    if not source_log:
        raise HTTPException(status_code=404, detail="日志不存在")

    # 获取原始模型名称
    original_model_result = await db.execute(
        select(Model.name).where(Model.id == source_log.model_id)
    )
    original_model_name = original_model_result.scalar_one_or_none()

    # 对每个目标模型执行回放
    replay_results = []
    for target_model_id in data.target_model_ids:
        try:
            result = await replay_log(
                log_id=data.log_id,
                data=ReplayRequest(target_model_id=target_model_id),
                db=db
            )
            replay_results.append(result)
        except HTTPException as e:
            # 获取模型名称
            model_result = await db.execute(
                select(Model.name).where(Model.id == target_model_id)
            )
            model_name = model_result.scalar_one_or_none()
            replay_results.append({
                "log_id": data.log_id,
                "original_response": source_log.response,
                "original_model_id": source_log.model_id,
                "original_model_name": original_model_name,
                "replay_model_id": target_model_id,
                "replay_model_name": model_name,
                "replay_response": None,
                "replay_latency_ms": None,
                "replay_status": "failed",
                "replay_error": e.detail,
            })

    return {
        "log_id": data.log_id,
        "original_prompt": source_log.prompt,
        "original_response": source_log.response,
        "original_model_name": original_model_name,
        "results": replay_results,
    }


@router.delete("/{log_id}")
async def delete_log(
    log_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """删除日志"""
    result = await db.execute(
        select(ModelRequestLog).where(ModelRequestLog.id == log_id)
    )
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")

    await db.delete(log)
    await db.commit()
    return {"message": "删除成功"}


@router.get("/stats", response_model=LogStatsResponse)
async def get_stats(
    model_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取日志统计信息"""
    # 基础查询
    base_query = select(ModelRequestLog)
    if model_id:
        base_query = base_query.where(ModelRequestLog.model_id == model_id)

    # 总数
    total_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total_logs = total_result.scalar() or 0

    # 按模型统计
    model_stats_result = await db.execute(
        select(ModelRequestLog.model_id, func.count())
        .group_by(ModelRequestLog.model_id)
    )
    logs_by_model = {str(row[0]): row[1] for row in model_stats_result}

    # 按类型统计
    type_stats_result = await db.execute(
        select(ModelRequestLog.request_type, func.count())
        .group_by(ModelRequestLog.request_type)
    )
    logs_by_type = {row[0]: row[1] for row in type_stats_result}

    # 按状态统计
    status_stats_result = await db.execute(
        select(ModelRequestLog.status, func.count())
        .group_by(ModelRequestLog.status)
    )
    logs_by_status = {row[0]: row[1] for row in status_stats_result}

    # 平均延迟
    avg_latency_result = await db.execute(
        select(func.avg(ModelRequestLog.latency_ms))
        .where(ModelRequestLog.latency_ms.isnot(None))
    )
    avg_latency_ms = avg_latency_result.scalar()

    # 回放数量
    replay_count_result = await db.execute(
        select(func.count()).where(ModelRequestLog.is_replay == True)
    )
    replay_count = replay_count_result.scalar() or 0

    return {
        "total_logs": total_logs,
        "logs_by_model": logs_by_model,
        "logs_by_type": logs_by_type,
        "logs_by_status": logs_by_status,
        "avg_latency_ms": float(avg_latency_ms) if avg_latency_ms else None,
        "replay_count": replay_count,
    }