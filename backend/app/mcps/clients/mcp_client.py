"""
MCP client 入口 - 统一调用所有 server 的工具
agent 代码用 MCPClient().call(server, tool, params) 而非直接调函数,使 server 可替换
也作为 LLM tool-calling(Function Calling)的入口:tools 列表由 list_openai_tools() 提供
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional
import logging

from app.mcps.registry import get_registry, MCPRegistry

logger = logging.getLogger(__name__)


class MCPClient:
    """MCP 进程内 client 封装"""

    def __init__(self, registry: Optional[MCPRegistry] = None):
        self.registry = registry or get_registry()

    async def call(self, server: str, tool: str, **params) -> Dict[str, Any]:
        """统一调用:返回 {ok, data} 或 {ok: false, error}"""
        logger.info(f"[MCPClient] call {server}.{tool} params={list(params.keys())}")
        return await self.registry.call_tool(server, tool, params)

    def list_servers(self) -> List[Dict[str, Any]]:
        return self.registry.list_servers()

    def list_tools(self) -> List[Dict[str, Any]]:
        """列出所有工具(server/name/description/schema),供 LLM Function calling 用"""
        return self.registry.list_all_tools()

    def list_openai_tools(self) -> List[Dict[str, Any]]:
        """转换为 OpenAI tools 格式(供 DeepSeek 兼容 client 使用 tool_choice=auto)"""
        tools = []
        for t in self.list_tools():
            tools.append({
                "type": "function",
                "function": {
                    "name": f"{t['server']}__{t['name']}",
                    "description": f"[{t['server']}] {t['description']}",
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            })
        return tools

    @staticmethod
    def parse_openai_tool_name(name: str) -> tuple[str, str]:
        """反解 OpenAI tool 名为 (server, tool)"""
        if "__" in name:
            s, t = name.split("__", 1)
            return s, t
        return "", name

    async def __call__(self, server: str, tool: str, **params) -> Dict[str, Any]:
        return await self.call(server, tool, **params)


_client_singleton: Optional[MCPClient] = None


def get_mcp_client() -> MCPClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = MCPClient()
    return _client_singleton
