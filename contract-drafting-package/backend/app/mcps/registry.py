"""
MCP server 注册中心 - 进程内单例

启动时由 mcps.__init__ 把所有 server 实例注册进来,client 通过
call_tool(server_name, tool_name, params) 调用。
list_servers / list_tools 用于暴露给前端/调试。
"""
from __future__ import annotations
from typing import Dict, List, Any, Optional
import logging

from .base_server import BaseMCPServer

logger = logging.getLogger(__name__)


class MCPRegistry:
    _instance: Optional["MCPRegistry"] = None
    _servers: Dict[str, BaseMCPServer]

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._servers = {}
        return cls._instance

    def register(self, server: BaseMCPServer) -> None:
        self._servers[server.name] = server
        logger.info(f"[MCP registry] registered server: {server.name} "
                    f"with {len(server._tools)} tools")

    def get(self, server_name: str) -> Optional[BaseMCPServer]:
        return self._servers.get(server_name)

    def list_servers(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "tool_count": len(s._tools),
                "tools": s.get_tool_names(),
            }
            for s in self._servers.values()
        ]

    def list_all_tools(self) -> List[Dict[str, Any]]:
        out = []
        for s in self._servers.values():
            for t in s.list_tools():
                out.append({"server": s.name, **t})
        return out

    async def call_tool(self, server_name: str, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """统一入口:server.call(tool, params)"""
        s = self.get(server_name)
        if not s:
            return {"ok": False, "error": f"unknown MCP server: {server_name}"}
        return await s.call(tool_name, params)


# 全局访问点
def get_registry() -> MCPRegistry:
    return MCPRegistry()
