"""
MCP HTTP 路由 - 暴露 MCP tool 给前端/调试/外部系统调用
GET  /api/mcp/servers            - 列出所有 server
GET  /api/mcp/tools              - 列出所有 tool(skill 详情给 LLM 用)
POST /api/mcp/{server}/{tool}     - 调用 tool,body = JSON 参数
"""
import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Path, Body, Depends

from app.mcps import register_default_servers, get_registry
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

# 启动时强制注册一次(幂等)
register_default_servers()


CORE_MCP_SERVERS = {
    "template_server",
    "enterprise_data_server",
    "vector_search_server",
    "qwen_server",
    "asr_server",
    "yolo_server",
}


@router.get("/servers")
async def list_servers(core_only: bool = True, current_user: Any = Depends(get_current_user)) -> Dict[str, Any]:
    """列出 MCP server；默认只展示最终架构中的核心 MCP。"""
    servers = get_registry().list_servers()
    if core_only:
        servers = [server for server in servers if server["name"] in CORE_MCP_SERVERS]
    return {
        "ok": True,
        "core_only": core_only,
        "data": servers,
    }


@router.get("/tools")
async def list_all_tools(core_only: bool = True, current_user: Any = Depends(get_current_user)) -> Dict[str, Any]:
    """列出 MCP tool；默认只展示最终架构中的核心 MCP 工具。"""
    tools = get_registry().list_all_tools()
    if core_only:
        tools = [tool for tool in tools if tool["server"] in CORE_MCP_SERVERS]
    return {
        "ok": True,
        "core_only": core_only,
        "data": tools,
    }


@router.post("/{server_name}/{tool_name}")
async def call_tool(
    server_name: str = Path(..., description="MCP server name,如 template_server"),
    tool_name: str = Path(..., description="tool name,如 get_template"),
    params: Dict[str, Any] = Body(default_factory=dict, description="tool 参数,JSON 对象"),
    current_user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    """调用 MCP tool,内部按 JSON-RPC 风格转发"""
    resp = await get_registry().call_tool(server_name, tool_name, params or {})
    if not resp.get("ok"):
        raise HTTPException(status_code=400, detail=resp)
    return resp
