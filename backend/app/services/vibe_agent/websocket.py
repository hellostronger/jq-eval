# WebSocket 连接管理
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Any, Optional
from datetime import datetime
import json
import asyncio


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        # 活动连接: session_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        # 连接元数据: session_id -> metadata
        self.connection_metadata: Dict[str, Dict[str, Any]] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        """建立 WebSocket 连接"""
        await websocket.accept()
        self.active_connections[session_id] = websocket
        self.connection_metadata[session_id] = {
            "connected_at": datetime.utcnow().isoformat(),
            "last_activity": datetime.utcnow().isoformat(),
        }

    def disconnect(self, session_id: str):
        """断开连接"""
        if session_id in self.active_connections:
            del self.active_connections[session_id]
        if session_id in self.connection_metadata:
            del self.connection_metadata[session_id]

    async def send_message(self, session_id: str, message: Dict[str, Any]):
        """发送消息"""
        if session_id in self.active_connections:
            websocket = self.active_connections[session_id]
            try:
                await websocket.send_json(message)
                self.connection_metadata[session_id]["last_activity"] = datetime.utcnow().isoformat()
            except Exception as e:
                # 连接可能已断开
                self.disconnect(session_id)
                raise e

    async def stream_response(self, session_id: str, response_type: str, content: str, metadata: Dict = None):
        """
        流式发送响应（模拟流式输出）

        Args:
            session_id: 会话 ID
            response_type: 响应类型 (clarification/preview/error/node_update)
            content: 内容
            metadata: 元数据
        """
        message = {
            "type": response_type,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata or {},
        }
        await self.send_message(session_id, message)

    async def send_slots_update(self, session_id: str, slots: list, workflow_type: str = None):
        """发送槽位更新"""
        message = {
            "type": "slots_update",
            "slots": slots,
            "workflow_type": workflow_type,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self.send_message(session_id, message)

    async def send_workflow_generated(self, session_id: str, workflow_def: Dict, python_code: str, mermaid: str):
        """发送工作流生成完成"""
        message = {
            "type": "workflow_generated",
            "workflow_definition": workflow_def,
            "python_code": python_code,
            "mermaid_diagram": mermaid,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self.send_message(session_id, message)

    async def send_error(self, session_id: str, error_message: str, error_code: str = None):
        """发送错误消息"""
        message = {
            "type": "error",
            "error_message": error_message,
            "error_code": error_code,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self.send_message(session_id, message)

    async def send_execution_update(self, session_id: str, execution_status: str, node_id: str = None, result: Any = None):
        """发送执行状态更新"""
        message = {
            "type": "execution_update",
            "status": execution_status,
            "node_id": node_id,
            "result": result,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self.send_message(session_id, message)

    def is_connected(self, session_id: str) -> bool:
        """检查是否已连接"""
        return session_id in self.active_connections

    def get_connection_count(self) -> int:
        """获取连接数量"""
        return len(self.active_connections)


class WebSocketHandler:
    """WebSocket 消息处理器"""

    def __init__(self, manager: ConnectionManager, engine):
        """
        Args:
            manager: 连接管理器
            engine: VibeAgentEngine 实例
        """
        self.manager = manager
        self.engine = engine

    async def handle_connection(self, websocket: WebSocket, session_id: str):
        """处理 WebSocket 连接生命周期"""
        await self.manager.connect(session_id, websocket)

        try:
            # 发送连接成功消息
            await self.manager.send_message(session_id, {
                "type": "connected",
                "session_id": session_id,
                "message": "WebSocket 连接成功",
            })

            # 消息循环
            while True:
                # 接收消息
                data = await websocket.receive_json()

                # 处理消息
                await self.handle_message(session_id, data)

        except WebSocketDisconnect:
            self.manager.disconnect(session_id)
        except Exception as e:
            await self.manager.send_error(session_id, str(e))
            self.manager.disconnect(session_id)

    async def handle_message(self, session_id: str, data: Dict[str, Any]):
        """处理接收的消息"""
        message_type = data.get("type", "unknown")
        content = data.get("content", "")
        metadata = data.get("metadata", {})

        try:
            if message_type == "start":
                # 开始新会话
                description = content
                result = await self.engine.start_session(session_id, description)

                if result["type"] == "clarification":
                    await self.manager.stream_response(session_id, "clarification", result["message"])
                    await self.manager.send_slots_update(session_id, result["slots"], result.get("workflow_type"))
                elif result["type"] == "preview":
                    await self.manager.stream_response(session_id, "preview", result["message"])
                    await self.manager.send_slots_update(session_id, result["slots"])

            elif message_type == "user_message":
                # 用户消息
                result = await self.engine.process_input(session_id, content)

                if result["type"] == "clarification":
                    await self.manager.stream_response(session_id, "clarification", result["message"])
                    await self.manager.send_slots_update(session_id, result["slots"])
                elif result["type"] == "preview":
                    await self.manager.stream_response(session_id, "preview", result["message"])
                    await self.manager.send_slots_update(session_id, result["slots"])
                elif result["type"] == "generate_request":
                    await self.manager.stream_response(session_id, "progress", "正在生成工作流...")
                    # 触发工作流生成
                    workflow_result = await self.engine.generate_workflow(session_id)
                    await self.manager.send_workflow_generated(
                        session_id,
                        workflow_result["workflow_definition"],
                        workflow_result["python_code"],
                        workflow_result["mermaid_diagram"]
                    )

            elif message_type == "generate":
                # 用户请求生成工作流
                await self.manager.stream_response(session_id, "progress", "正在生成工作流...")
                workflow_result = await self.engine.generate_workflow(session_id)
                await self.manager.send_workflow_generated(
                    session_id,
                    workflow_result["workflow_definition"],
                    workflow_result["python_code"],
                    workflow_result["mermaid_diagram"]
                )

            elif message_type == "execute":
                # 执行工作流
                workflow_id = data.get("workflow_id")
                input_data = data.get("input_data", {})
                await self.manager.send_execution_update(session_id, "started")
                result = await self.engine.execute_workflow(workflow_id, input_data)
                await self.manager.send_execution_update(session_id, "completed", result=result)

            elif message_type == "ping":
                # 心跳
                await self.manager.send_message(session_id, {"type": "pong"})

            else:
                await self.manager.send_error(session_id, f"未知消息类型: {message_type}")

        except Exception as e:
            await self.manager.send_error(session_id, f"处理消息时出错: {str(e)}")


# 全局连接管理器实例
connection_manager = ConnectionManager()


def get_connection_manager() -> ConnectionManager:
    """获取连接管理器实例"""
    return connection_manager