"""A2A JSON-RPC 服务端：把任意 async handler 包装成符合 A2A 规范的 agent 服务。

handler 签名: async def handler(message_text: str, task_id: str) -> Dict[str, Any]
返回的结构化 dict 会作为 Task artifact 的 text part 回传（JSON 序列化）。
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.a2a.code_version import compute_agent_code_version
from app.a2a.protocol import AgentCard
from app.core.config import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)

A2A_TOKEN_HEADER = "x-a2a-token"

AgentHandler = Callable[[str, str], Awaitable[Dict[str, Any]]]

# JSON-RPC 2.0 标准错误码
RPC_PARSE_ERROR = -32700
RPC_INVALID_REQUEST = -32600
RPC_METHOD_NOT_FOUND = -32601
RPC_INVALID_PARAMS = -32602
RPC_INTERNAL_ERROR = -32603


def _rpc_result(rpc_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _rpc_error(rpc_id: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    err: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rpc_id, "error": err}


def _extract_message_text(message: Dict[str, Any]) -> str:
    """从 A2A Message 里取出全部 text part 内容并拼接。

    兼容 v0.3 的 parts[].kind 与旧版 parts[].type 两种写法。
    """
    parts: List[Any] = message.get("parts") or []
    chunks: List[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        kind = part.get("kind") or part.get("type") or "text"
        if kind == "text" and isinstance(part.get("text"), str):
            chunks.append(part["text"])
    return "\n".join(c for c in chunks if c)


def build_a2a_app(card: AgentCard, handler: AgentHandler) -> FastAPI:
    app = FastAPI(title=f"A2A Agent: {card.name}", docs_url=None, redoc_url=None)
    # Task 存储（stateTransitionHistory capability：tasks/get 可查）
    tasks: Dict[str, Dict[str, Any]] = {}

    @app.get("/.well-known/agent-card.json")
    async def agent_card() -> Dict[str, Any]:
        """A2A 发现机制：能力名片。"""
        return card.to_dict()

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {
            "status": "healthy",
            "agent": card.name,
            "protocol": f"A2A/{card.protocol_version}",
            "code_version": compute_agent_code_version(),
        }

    def _check_token(request: Request) -> Optional[JSONResponse]:
        """可选鉴权：.env 配置 A2A_TOKEN 后，message/send 必须带同值 X-A2A-Token 头。"""
        expected = (settings.A2A_TOKEN or "").strip()
        if not expected:
            return None
        if (request.headers.get(A2A_TOKEN_HEADER) or "") != expected:
            return JSONResponse(_rpc_error(None, RPC_INVALID_REQUEST, "Invalid or missing A2A token"), status_code=200)
        return None

    @app.post("/")
    async def jsonrpc_endpoint(request: Request) -> JSONResponse:
        token_error = _check_token(request)
        if token_error is not None:
            return token_error
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(_rpc_error(None, RPC_PARSE_ERROR, "Parse error"), status_code=400)

        rpc_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}

        if method == "message/send":
            message = params.get("message") or {}
            text = _extract_message_text(message)
            task_id = (
                message.get("taskId")
                or params.get("taskId")
                or message.get("messageId")
                or uuid.uuid4().hex
            )
            context_id = message.get("contextId") or uuid.uuid4().hex
            task: Dict[str, Any] = {
                "id": task_id,
                "contextId": context_id,
                "kind": "task",
                "status": {"state": "working", "timestamp": datetime.now().isoformat()},
                "artifacts": [],
                "history": [{
                    "role": message.get("role", "user"),
                    "parts": message.get("parts") or [],
                    "messageId": message.get("messageId") or uuid.uuid4().hex,
                    "taskId": task_id,
                    "contextId": context_id,
                    "kind": "message",
                }],
            }
            tasks[task_id] = task
            try:
                if not text:
                    raise ValueError("message/send 缺少 text part")
                result_payload = await handler(text, task_id)
            except Exception as exc:
                logger.exception("A2A agent %s 执行失败 (task=%s)", card.name, task_id)
                task["status"] = {"state": "failed", "timestamp": datetime.now().isoformat()}
                task["error"] = {"code": RPC_INTERNAL_ERROR, "message": str(exc)}
                return JSONResponse(_rpc_error(
                    rpc_id, RPC_INTERNAL_ERROR, "Internal error",
                    data={"agent": card.name, "taskId": task_id, "detail": str(exc)},
                ), status_code=200)

            task["status"] = {"state": "completed", "timestamp": datetime.now().isoformat()}
            task["artifacts"] = [{
                "artifactId": uuid.uuid4().hex,
                "taskId": task_id,
                "name": "result",
                "description": f"{card.name} structured result",
                "parts": [{
                    "kind": "text",
                    "text": json.dumps(result_payload, ensure_ascii=False, default=str),
                }],
            }]
            return JSONResponse(_rpc_result(rpc_id, task))

        if method == "tasks/get":
            task_id = params.get("id") or ""
            if task_id in tasks:
                return JSONResponse(_rpc_result(rpc_id, tasks[task_id]))
            return JSONResponse(_rpc_error(rpc_id, RPC_INVALID_PARAMS, f"Task not found: {task_id}"))

        return JSONResponse(_rpc_error(rpc_id, RPC_METHOD_NOT_FOUND, f"Method not supported: {method}"))

    return app
