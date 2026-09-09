"""
MCP 协议定义 - 进程内简化版 MCP(Model Context Protocol)

外部 MCP 协议基于 JSON-RPC over stdio/SSE。本项目内实现的精简版：
- 每个 tool 暴露为 {name, description, input_schema, handler} 注册项
- 调用格式参照 JSON-RPC: {server, tool, params} -> {ok, data} | {ok: false, error}
- 同时支持进程内直接调用 (call_tool) 与 HTTP endpoint 调用 (POST /api/mcp/{server}/{tool})

这样既契合 MCP 语义,又无需引入额外 SDK。
"""
from __future__ import annotations
from typing import Any, Dict, Optional, Callable, List
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolSchema:
    """MCP 工具 schema(简化)"""
    name: str                               # 工具名,如 get_template
    description: str                        # 自然语言描述(给 LLM 看)
    input_schema: Dict[str, Any]            # 参数 JSON Schema(简化版仅用 properties/required)
    handler: Callable[..., Dict[str, Any]]  # 实际执行函数,async OK

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class MCPRequest:
    """统一请求格式:JSON-RPC 风格"""
    def __init__(self, server: str, tool: str, params: Optional[Dict[str, Any]] = None, request_id: Optional[str] = None):
        self.server = server
        self.tool = tool
        self.params = params or {}
        self.id = request_id


class MCPResponse:
    """统一响应格式"""
    def __init__(self, ok: bool, data: Any = None, error: Optional[str] = None, request_id: Optional[str] = None):
        self.ok = ok
        self.data = data
        self.error = error
        self.id = request_id

    def to_dict(self) -> Dict[str, Any]:
        d = {"ok": self.ok, "id": self.id}
        if self.ok:
            d["data"] = self.data
        else:
            d["error"] = self.error
        return d


def validate_params(schema: Dict[str, Any], params: Dict[str, Any]) -> Optional[str]:
    """极简参数校验:按 schema.required 校验必填项是否齐,不校验类型(MCP SDK 默认行为)
    返回 None 表示通过,返回字符串为错误描述
    """
    required = schema.get("required", []) or []
    missing = [k for k in required if k not in params or params[k] is None or params[k] == ""]
    if missing:
        return f"missing required params: {', '.join(missing)}"
    return None
