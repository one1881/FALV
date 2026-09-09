"""A2A（Agent-to-Agent）协议层。

按 Google A2A 官方规范（protocolVersion 0.3.x，JSONRPC transport）实现：
- Agent Card：GET /.well-known/agent-card.json，声明 agent 能力（发现机制）
- JSON-RPC 2.0 端点：method = message/send / tasks/get
- Task 产物：artifacts[].parts[]，state = completed / failed

协议是 A2A 的本质：本实现为无外部 SDK 依赖的规范实现，与官方 a2a-sdk
客户端可直接互操作（任何标准 A2A client 都能发现并调用这些 agent）。
"""
from app.a2a.client import A2AError, A2AClient
from app.a2a.protocol import AgentCard
from app.a2a.server import build_a2a_app

__all__ = ["A2AError", "A2AClient", "AgentCard", "build_a2a_app"]
