# VibeAgent API 路由
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from uuid import uuid4
import os

from ...services.vibe_agent import (
    VibeAgentEngine,
    get_engine,
    ConnectionManager,
    WebSocketHandler,
    get_connection_manager,
)
from ...models.vibe_agent import (
    VibeAgentSession,
    VibeAgentWorkflow,
    VibeAgentWorkflowVersion,
    VibeAgentExecution,
    VibeAgentNodeConfig,
)
from ...core.database import AsyncSessionLocal, get_db
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/vibe-agent", tags=["VibeAgent"])


# ========== Pydantic Schema ==========

class CreateSessionRequest(BaseModel):
    """创建会话请求"""
    description: str
    llm_config: Optional[Dict[str, Any]] = None


class SendMessageRequest(BaseModel):
    """发送消息请求"""
    message: str


class UpdateWorkflowConfigRequest(BaseModel):
    """更新工作流配置请求"""
    name: Optional[str] = None
    llm_config: Optional[Dict[str, Any]] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None


class ExecuteWorkflowRequest(BaseModel):
    """执行工作流请求"""
    input_data: Dict[str, Any]
    workflow_version_id: Optional[str] = None


class TuneNodeRequest(BaseModel):
    """节点调优请求"""
    node_id: str
    feedback: Dict[str, Any]


class SaveWorkflowRequest(BaseModel):
    """保存工作流请求"""
    session_id: str
    name: str
    description: Optional[str] = None


# ========== REST API ==========

@router.post("/sessions", response_model=Dict[str, Any])
async def create_session(request: CreateSessionRequest):
    """创建新会话"""
    session_id = str(uuid4())

    # 获取或创建引擎
    llm_config = request.llm_config or {
        "api_url": os.getenv("OPENAI_API_URL", "https://api.openai.com/v1"),
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "temperature": 0.7,
    }
    engine = create_engine(llm_config)

    # 创建数据库会话记录
    async with AsyncSessionLocal() as db:
        db_session = VibeAgentSession(
            id=session_id,
            original_description=request.description,
            status="active",
            llm_config=llm_config,
        )
        db.add(db_session)
        await db.commit()

    # 启动引擎会话
    result = await engine.start_session(session_id, request.description)

    # 更新数据库
    async with AsyncSessionLocal() as db:
        await db.execute(
            select(VibeAgentSession).where(VibeAgentSession.id == session_id)
        )
        db_session.collected_info = engine.get_session_state(session_id).to_dict()
        await db.commit()

    return {
        "session_id": session_id,
        "result": result,
    }


@router.get("/sessions/{session_id}", response_model=Dict[str, Any])
async def get_session(session_id: str):
    """获取会话详情"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(VibeAgentSession).where(VibeAgentSession.id == session_id)
        )
        session = result.scalar_one_or_none()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return {
            "session_id": str(session.id),
            "status": session.status,
            "original_description": session.original_description,
            "collected_info": session.collected_info,
            "conversation_history": session.conversation_history,
            "created_at": session.created_at.isoformat(),
        }


@router.post("/sessions/{session_id}/messages", response_model=Dict[str, Any])
async def send_message(session_id: str, request: SendMessageRequest):
    """发送消息（HTTP 方式，备用）"""
    engine = get_engine()

    if not engine.get_session_state(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    result = await engine.process_input(session_id, request.message)

    # 更新数据库
    async with AsyncSessionLocal() as db:
        db_result = await db.execute(
            select(VibeAgentSession).where(VibeAgentSession.id == session_id)
        )
        db_session = db_result.scalar_one_or_none()
        if db_session:
            state = engine.get_session_state(session_id)
            db_session.collected_info = state.to_dict()
            db_session.conversation_history = state.conversation_history
            await db.commit()

    return result


@router.post("/sessions/{session_id}/generate", response_model=Dict[str, Any])
async def generate_workflow(session_id: str):
    """生成工作流"""
    engine = get_engine()

    if not engine.get_session_state(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    result = await engine.generate_workflow(session_id)

    return result


@router.get("/workflows", response_model=List[Dict[str, Any]])
async def list_workflows():
    """获取工作流列表"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(VibeAgentWorkflow).where(VibeAgentWorkflow.is_active == True).order_by(VibeAgentWorkflow.created_at.desc())
        )
        workflows = result.scalars().all()

        return [
            {
                "id": str(w.id),
                "name": w.name,
                "description": w.description,
                "status": w.status,
                "execution_count": w.execution_count,
                "version_count": w.version_count,
                "created_at": w.created_at.isoformat(),
            }
            for w in workflows
        ]


@router.get("/workflows/{workflow_id}", response_model=Dict[str, Any])
async def get_workflow(workflow_id: str):
    """获取工作流详情"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(VibeAgentWorkflow).where(VibeAgentWorkflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        return {
            "id": str(workflow.id),
            "name": workflow.name,
            "description": workflow.description,
            "graph_definition": workflow.graph_definition,
            "nodes": workflow.nodes,
            "edges": workflow.edges,
            "python_code": workflow.python_code,
            "mermaid_diagram": workflow.mermaid_diagram,
            "llm_config": workflow.llm_config,
            "status": workflow.status,
            "created_at": workflow.created_at.isoformat(),
        }


@router.post("/workflows", response_model=Dict[str, Any])
async def save_workflow(request: SaveWorkflowRequest):
    """保存工作流到数据库"""
    engine = get_engine()

    workflow_data = engine.get_workflow(request.session_id)
    if not workflow_data:
        raise HTTPException(status_code=404, detail="Workflow data not found in session")

    workflow_id = str(uuid4())

    async with AsyncSessionLocal() as db:
        workflow = VibeAgentWorkflow(
            id=workflow_id,
            session_id=request.session_id,
            name=request.name,
            description=request.description,
            graph_definition=workflow_data["workflow_definition"],
            nodes=workflow_data["workflow_definition"].get("nodes", []),
            edges=workflow_data["workflow_definition"].get("edges", []),
            python_code=workflow_data["python_code"],
            mermaid_diagram=workflow_data["mermaid_diagram"],
            llm_config=engine.llm_config,
            status="ready",
        )
        db.add(workflow)

        # 创建初始版本
        version = VibeAgentWorkflowVersion(
            workflow_id=workflow_id,
            version=1,
            graph_definition=workflow_data["workflow_definition"],
            nodes=workflow_data["workflow_definition"].get("nodes", []),
            edges=workflow_data["workflow_definition"].get("edges", []),
            python_code=workflow_data["python_code"],
            mermaid_diagram=workflow_data["mermaid_diagram"],
            change_type="create",
            change_notes="初始创建",
        )
        db.add(version)

        await db.commit()

    return {
        "workflow_id": workflow_id,
        "message": "Workflow saved successfully",
    }


@router.put("/workflows/{workflow_id}/config", response_model=Dict[str, Any])
async def update_workflow_config(workflow_id: str, request: UpdateWorkflowConfigRequest):
    """更新工作流配置（参数调优）"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(VibeAgentWorkflow).where(VibeAgentWorkflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # 更新配置
        if request.name:
            workflow.name = request.name
        if request.llm_config:
            workflow.llm_config = request.llm_config
        if request.nodes:
            workflow.nodes = request.nodes
        if request.edges:
            workflow.edges = request.edges

        # 创建新版本
        version_num = workflow.version_count + 1
        version = VibeAgentWorkflowVersion(
            workflow_id=workflow_id,
            version=version_num,
            graph_definition={"nodes": workflow.nodes, "edges": workflow.edges},
            nodes=workflow.nodes,
            edges=workflow.edges,
            python_code=workflow.python_code,
            mermaid_diagram=workflow.mermaid_diagram,
            change_type="update",
            change_notes="配置更新",
        )
        db.add(version)

        workflow.version_count = version_num
        await db.commit()

        return {
            "workflow_id": workflow_id,
            "version": version_num,
            "message": "Config updated successfully",
        }


@router.post("/workflows/{workflow_id}/execute", response_model=Dict[str, Any])
async def execute_workflow(workflow_id: str, request: ExecuteWorkflowRequest):
    """执行工作流"""
    engine = get_engine()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(VibeAgentWorkflow).where(VibeAgentWorkflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # 创建执行记录
        execution_id = str(uuid4())
        execution = VibeAgentExecution(
            id=execution_id,
            workflow_id=workflow_id,
            workflow_version_id=request.workflow_version_id,
            input_data=request.input_data,
            status="running",
        )
        db.add(execution)
        workflow.status = "executing"
        workflow.execution_count += 1
        await db.commit()

    # 执行工作流
    try:
        # 将 workflow 数据缓存到引擎
        engine.workflow_cache[workflow_id] = {
            "workflow_definition": workflow.graph_definition,
            "python_code": workflow.python_code,
        }
        result = await engine.execute_workflow(workflow_id, request.input_data)

        # 更新执行记录
        async with AsyncSessionLocal() as db:
            await db.execute(
                select(VibeAgentExecution).where(VibeAgentExecution.id == execution_id)
            )
            execution.status = result.get("status", "failed")
            execution.output_data = result.get("result", {})
            execution.error_message = result.get("error")
            execution.execution_time = result.get("execution_time")

            await db.execute(
                select(VibeAgentWorkflow).where(VibeAgentWorkflow.id == workflow_id)
            )
            workflow.status = "ready"
            await db.commit()

        return {
            "execution_id": execution_id,
            "status": result.get("status"),
            "result": result.get("result"),
            "execution_time": result.get("execution_time"),
        }

    except Exception as e:
        async with AsyncSessionLocal() as db:
            await db.execute(
                select(VibeAgentExecution).where(VibeAgentExecution.id == execution_id)
            )
            execution.status = "failed"
            execution.error_message = str(e)
            await db.commit()

        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workflows/{workflow_id}/tune", response_model=Dict[str, Any])
async def tune_node(workflow_id: str, request: TuneNodeRequest):
    """节点调优"""
    engine = get_engine()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(VibeAgentWorkflow).where(VibeAgentWorkflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # 缓存到引擎
        engine.workflow_cache[workflow_id] = {
            "workflow_definition": workflow.graph_definition,
            "python_code": workflow.python_code,
        }

    result = await engine.tune_node(workflow_id, request.node_id, request.feedback)

    # 更新数据库中的节点配置
    async with AsyncSessionLocal() as db:
        # 更新 workflow 中的节点
        nodes = workflow.nodes
        for i, node in enumerate(nodes):
            if node.get("id") == request.node_id:
                nodes[i]["config"] = result.get("updated_config", {})
                break
        workflow.nodes = nodes

        # 更新节点配置表
        node_config_result = await db.execute(
            select(VibeAgentNodeConfig).where(
                VibeAgentNodeConfig.workflow_id == workflow_id,
                VibeAgentNodeConfig.node_id == request.node_id
            )
        )
        node_config = node_config_result.scalar_one_or_none()
        if node_config:
            node_config.config = result.get("updated_config", {})
            if result.get("optimization_result", {}).get("prompt_suggestion"):
                node_config.prompt_template = result["optimization_result"]["prompt_suggestion"]

        await db.commit()

    return result


@router.get("/workflows/{workflow_id}/versions", response_model=List[Dict[str, Any]])
async def get_workflow_versions(workflow_id: str):
    """获取工作流版本历史"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(VibeAgentWorkflowVersion)
            .where(VibeAgentWorkflowVersion.workflow_id == workflow_id)
            .order_by(VibeAgentWorkflowVersion.version.desc())
        )
        versions = result.scalars().all()

        return [
            {
                "id": str(v.id),
                "version": v.version,
                "change_type": v.change_type,
                "change_notes": v.change_notes,
                "mermaid_diagram": v.mermaid_diagram,
                "created_at": v.created_at.isoformat(),
            }
            for v in versions
        ]


@router.post("/workflows/{workflow_id}/test", response_model=Dict[str, Any])
async def test_workflow(workflow_id: str, test_cases: Optional[List[Dict[str, Any]]] = None):
    """测试工作流代码"""
    engine = get_engine()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(VibeAgentWorkflow).where(VibeAgentWorkflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")

        # 缓存到引擎
        engine.workflow_cache[workflow_id] = {
            "workflow_definition": workflow.graph_definition,
            "python_code": workflow.python_code,
        }

    test_result = await engine.test_workflow(workflow_id, test_cases)

    return test_result


# ========== WebSocket ==========

@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket 连接端点"""
    manager = get_connection_manager()
    engine = get_engine()

    handler = WebSocketHandler(manager, engine)

    await handler.handle_connection(websocket, session_id)