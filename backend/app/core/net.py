"""代理绝缘 HTTP 客户端工厂 —— 全局唯一实现（2026-09-12）。

背景（2026-09-10 事故，两起）：
沙箱 / 工具进程会向子进程注入 ``HTTP_PROXY=http://127.0.0.1:8279`` 之类的代理变量。
``httpx`` 与 ``openai`` / ``langchain_openai`` SDK 默认 ``trust_env=True``，会把发往
DashScope 的请求绕经该死代理 → 请求挂死直到 ReadTimeout（实测单次起草卡满 50 分钟）。
另一起是 async 路由直调同步 SDK 冻结事件循环。

本模块是「代理绝缘」的唯一实现处。业务代码**不要**再直接写
``httpx.AsyncClient(timeout=...)``，一律从此处取；否则静态防复发检查
（``scripts/_check_proxy_immunity.py``）会失败。

两类使用方式：
- ``proxy_immune_clients(timeout)``：进程级复用（连接池共享），适合长期存活的客户端；
- ``new_proxy_immune_async_client(timeout)``：每次新建，配合 ``async with`` 短连接使用。
"""
from __future__ import annotations

import httpx

# 建连超时。给满长 timeout 的模型调用留出「连不上就快速失败」的能力，
# 避免 TCP 层静默 hang 住把整个预算吃光。
MODEL_CONNECT_TIMEOUT = 20.0

_SYNC_CLIENTS: "dict[float, httpx.Client]" = {}
_ASYNC_CLIENTS: "dict[float, httpx.AsyncClient]" = {}


def proxy_immune_timeout(timeout: float, connect: float | None = None) -> httpx.Timeout:
    """构造带独立 connect 超时的 ``httpx.Timeout``。"""
    return httpx.Timeout(float(timeout), connect=float(connect if connect is not None else MODEL_CONNECT_TIMEOUT))


def proxy_immune_clients(timeout: float = 600.0) -> "tuple[httpx.Client, httpx.AsyncClient]":
    """返回进程级复用的 (同步, 异步) 客户端对，均 ``trust_env=False``，按 timeout 分桶。"""
    key = float(timeout)
    if key not in _SYNC_CLIENTS:
        _SYNC_CLIENTS[key] = httpx.Client(trust_env=False, timeout=proxy_immune_timeout(key))
    if key not in _ASYNC_CLIENTS:
        _ASYNC_CLIENTS[key] = httpx.AsyncClient(trust_env=False, timeout=proxy_immune_timeout(key))
    return _SYNC_CLIENTS[key], _ASYNC_CLIENTS[key]


def proxy_immune_client(timeout: float = 600.0) -> httpx.Client:
    """同步客户端（进程级复用）。"""
    return proxy_immune_clients(timeout)[0]


def proxy_immune_async_client(timeout: float = 600.0) -> httpx.AsyncClient:
    """异步客户端（进程级复用）。

    注意：httpx.AsyncClient 绑定事件循环，仅在单事件循环进程（FastAPI / uvicorn）内复用安全。
    """
    return proxy_immune_clients(timeout)[1]


def new_proxy_immune_async_client(timeout: float = 600.0, connect: float | None = None) -> httpx.AsyncClient:
    """新建一个 ``trust_env=False`` 的异步客户端，配合 ``async with`` 用完即关。

    与 ``proxy_immune_async_client`` 的区别：不共享连接池，生命周期由调用方掌握，
    适合 MCP server 这类「一次工具调用开一次连接」的场景。
    """
    return httpx.AsyncClient(trust_env=False, timeout=proxy_immune_timeout(timeout, connect))
