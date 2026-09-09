"""
MCP server 基类 - 所有 server(template_server/legal_data_server 等)继承自此
每个 server 在 __init__ 中通过 register_tool 注册工具
"""
from __future__ import annotations
from typing import Dict, List, Callable, Any
import logging

from .protocol import ToolSchema, validate_params

logger = logging.getLogger(__name__)


class BaseMCPServer:
    """MCP server 基类"""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._tools: Dict[str, ToolSchema] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable[..., Any],
    ) -> None:
        """注册一个工具"""
        schema = ToolSchema(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
        )
        self._tools[name] = schema
        logger.info(f"[MCP:{self.name}] registered tool: {name}")

    async def call(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """server 内部 call:校验参数->调 handler
        handler 可以是 async 或同步,这里统一 await
        返回 dict = {ok, data} 或 {ok: false, error}
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return {"ok": False, "error": f"unknown tool '{tool_name}' on server '{self.name}'"}

        err = validate_params(tool.input_schema, params)
        if err:
            return {"ok": False, "error": f"[{self.name}.{tool_name}] {err}"}

        try:
            import asyncio
            result = tool.handler(**params)
            if asyncio.iscoroutine(result):
                result = await result
            return {"ok": True, "data": result}
        except Exception as e:
            logger.exception(f"[MCP:{self.name}.{tool_name}] handler error")
            return {"ok": False, "error": f"handler exception: {type(e).__name__}: {e}"}

    def list_tools(self) -> List[Dict[str, Any]]:
        """列出本 server 所有工具的元信息(MCP 标准方法 tools/list)"""
        return [t.to_dict() for t in self._tools.values()]

    def get_tool_names(self) -> List[str]:
        return list(self._tools.keys())
