"""MCP 协议层 - 提供统一调用入口 + 服务端进程内注册"""
import logging
from typing import List, Dict, Any

from .protocol import ToolSchema, MCPRequest, MCPResponse, validate_params
from .base_server import BaseMCPServer
from .registry import get_registry, MCPRegistry

logger = logging.getLogger(__name__)

__all__ = [
    "ToolSchema",
    "MCPRequest",
    "MCPResponse",
    "validate_params",
    "BaseMCPServer",
    "get_registry",
    "MCPRegistry",
    "register_default_servers",
    "register_servers",
    "list_tools",
    "list_servers",
]


def register_default_servers() -> int:
    """导入并注册所有内置 MCP server,返回注册的 tool 总数
    懒加载:首次调用时 import 各 server,避免循环引用
    """
    registry = get_registry()
    if registry.list_servers():  # 已注册过
        return sum(len(s["tools"]) for s in registry.list_servers())

    from .servers.template_server import TemplateServer
    from .servers.enterprise_data_server import EnterpriseDataServer
    from .servers.legal_data_server import LegalDataServer
    from .servers.vector_search_server import VectorSearchServer
    from .servers.mineru_server import MinerUServer
    from .servers.asr_server import ASRServer
    from .servers.yolo_server import YoloServer
    from .servers.qwen_server import QwenServer

    for cls in (
        TemplateServer,
        EnterpriseDataServer,
        LegalDataServer,
        VectorSearchServer,
        MinerUServer,
        ASRServer,
        YoloServer,
        QwenServer,
    ):
        registry.register(cls())

    logger.info(f"[MCP] registered {len(registry.list_servers())} servers, "
                f"{sum(len(s['tools']) for s in registry.list_servers())} tools")
    return sum(len(s["tools"]) for s in registry.list_servers())


def register_servers(server_instances: List[BaseMCPServer]) -> int:
    """手动注册一组 server(扩展用)"""
    registry = get_registry()
    for s in server_instances:
        registry.register(s)
    return len(server_instances)


def list_servers() -> List[Dict[str, Any]]:
    return get_registry().list_servers()


def list_tools() -> List[Dict[str, Any]]:
    return get_registry().list_all_tools()
